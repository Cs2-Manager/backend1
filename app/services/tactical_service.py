from copy import deepcopy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from app.extensions import db
from app.errors import ApiError
from app.models.tactics import TeamStrategy, StrategyRevision, TeamMapSetup
from app.models.lineup import Lineup
from app.permissions.policies import can_read_tactics, can_manage_tactics
from app.services import team_lineup_service as rosters
from app.services.map_service import get_map
from app.services import tactical_validation as validate
from app.serializers.tactics import strategy_payload


def access(user, team_id, write=False):
    team = rosters._get_team(team_id)
    role = rosters._role_for(user, team)
    policy = can_manage_tactics if write else can_read_tactics
    if not policy(user, role):
        raise ApiError('Team tactics are private', status_code=403)
    return team, role


def commit():
    try:
        db.session.commit()
    except (IntegrityError, StaleDataError) as error:
        db.session.rollback()
        raise ApiError('Resource changed concurrently; reload before saving', status_code=409) from error


def get(user, team_id, strategy_id, write=False):
    access(user, team_id, write)
    item = db.session.query(TeamStrategy).filter_by(id=strategy_id, team_id=team_id).first()
    if item is None:
        raise ApiError('Strategy not found', status_code=404)
    return item


def payload(user, item):
    team, role = access(user, item.team_id)
    members = {m.user_id for m in team.members}
    if item.lineup_id:
        lineup = rosters._get_lineup(item.team_id, item.lineup_id)
        members &= {p.user_id for p in lineup.players if p.is_starter}
        if lineup.map_id is not None and lineup.map_id != item.map_id:
            members = set()
    else:
        members = set()
    from app.services.lineup_service import visible_query
    grenades = {g.id for g in visible_query(user).filter_by(map_id=item.map_id).filter(db.or_(Lineup.team_id == item.team_id, Lineup.visibility == 'PUBLIC'))}
    return strategy_payload(item, member_ids=members, grenade_ids=grenades, can_edit=can_manage_tactics(user, role))


def listing(user, team_id, filters):
    team, role = access(user, team_id)
    query = db.session.query(TeamStrategy).filter_by(team_id=team_id)
    for field in ('map_id', 'side', 'category', 'status'):
        if filters.get(field):
            query = query.filter(getattr(TeamStrategy, field) == filters[field])
    if filters.get('q'):
        query = query.filter(TeamStrategy.name.icontains(filters['q'][:160], autoescape=True))
    items = query.order_by(TeamStrategy.updated_at.desc()).limit(200).all()
    from app.models.team_lineup import TeamLineupPlayer
    entries = db.session.query(TeamLineupPlayer).filter(TeamLineupPlayer.lineup_id.in_([s.lineup_id for s in items if s.lineup_id]), TeamLineupPlayer.is_starter.is_(True)).all()
    rosters_by_id = {}
    for entry in entries:
        rosters_by_id.setdefault(entry.lineup_id, set()).add(entry.user_id)
    members = {m.user_id for m in team.members}
    from app.services.lineup_service import visible_query
    grenade_map = {}
    for g in visible_query(user).filter(Lineup.map_id.in_([s.map_id for s in items])).filter(db.or_(Lineup.team_id == team_id, Lineup.visibility == 'PUBLIC')):
        grenade_map.setdefault(g.map_id, set()).add(g.id)
    return [strategy_payload(s, member_ids=members & rosters_by_id.get(s.lineup_id, set()), grenade_ids=grenade_map.get(s.map_id, set()), can_edit=can_manage_tactics(user, role)) for s in items]


def lineup_for(team_id, map_id, lineup_id):
    if lineup_id is None:
        return None
    if type(lineup_id) is not int:
        validate.invalid('Invalid lineup identifier')
    lineup = rosters._get_lineup(team_id, lineup_id)
    if lineup.map_id is not None and lineup.map_id != map_id:
        validate.invalid('Lineup belongs to another map')
    return lineup


def save(user, team_id, data, strategy_id=None, *, historical_restore=False):
    team, _ = access(user, team_id, True)
    validate.object_keys(data, ('map_id', 'lineup_id', 'name', 'description', 'side', 'category', 'status', 'version', 'document'))
    item = get(user, team_id, strategy_id, True) if strategy_id else None
    if item and data.get('version') != item.version:
        raise ApiError('Strategy version conflict', status_code=409)
    mid = data.get('map_id', item.map_id if item else None)
    if type(mid) is not int:
        validate.invalid('Invalid map')
    get_map(mid)
    lid = data.get('lineup_id', item.lineup_id if item else None)
    lineup = lineup_for(team_id, mid, lid)
    players = {p.user_id for p in lineup.players if p.is_starter} if lineup else set()
    players &= {m.user_id for m in team.members}
    from app.services.lineup_service import visible_query
    grenades = {g.id for g in visible_query(user).filter_by(map_id=mid).filter(db.or_(Lineup.team_id == team_id, Lineup.visibility == 'PUBLIC'))}
    values = {}
    for field, default, maximum in [('name', '', 160), ('description', '', 4000), ('side', 'T', 2), ('category', 'Default', 30), ('status', 'DRAFT', 12)]:
        values[field] = validate.text(data.get(field, getattr(item, field, default)), maximum)
    if not values['name'] or values['side'] not in ('CT', 'T') or values['category'] not in validate.CATEGORIES or values['status'] not in ('DRAFT', 'PUBLISHED', 'ARCHIVED'):
        validate.invalid('Invalid strategy metadata')
    raw = data.get('document', item.document if item else {'schema_version': 1, 'elements': [], 'steps': [], 'assignments': [], 'notes': ''})
    if historical_restore:
        # Only immutable server-side revisions may retain departed references.
        # The restored draft is explicitly marked for review by the serializer.
        players |= {e['user_id'] for e in raw.get('elements', []) if e.get('user_id')}
        players |= {a['user_id'] for a in raw.get('assignments', [])}
        for step in raw.get('steps', []):
            players.update(step.get('user_ids', []))
        for entry in raw.get('assignments', []) + raw.get('steps', []):
            grenades.update(entry.get('grenade_ids', []))
    values['document'] = deepcopy(validate.document(raw, players, grenades))
    if item is None:
        item = TeamStrategy(team_id=team_id, map_id=mid, author_id=user.id)
        db.session.add(item)
    else:
        db.session.add(StrategyRevision(strategy_id=item.id, version=item.version,
                       author_id=user.id, snapshot=strategy_payload(item)))
    for field, value in values.items():
        setattr(item, field, value)
    item.map_id, item.lineup_id = mid, lid
    # Force a version increment even for identical saves (revision uniqueness).
    if strategy_id:
        item.version += 1
    commit()
    return payload(user, item)


def duplicate(user, team_id, sid):
    item = get(user, team_id, sid, True)
    data = {k: deepcopy(getattr(item, k)) for k in ('map_id', 'lineup_id', 'name', 'description', 'side', 'category', 'document')}
    data['name'] = item.name[:150] + ' (copy)'
    return save(user, team_id, data)


def revisions(user, team_id, sid):
    get(user, team_id, sid)
    return [{'version': r.version, 'author_id': r.author_id, 'created_at': r.created_at.isoformat(), 'snapshot': r.snapshot}
            for r in db.session.query(StrategyRevision).filter_by(strategy_id=sid).order_by(StrategyRevision.version.desc())]


def restore(user, team_id, sid, version, current):
    get(user, team_id, sid, True)
    row = db.session.query(StrategyRevision).filter_by(strategy_id=sid, version=version).first()
    if not row:
        raise ApiError('Revision not found', status_code=404)
    data = {k: deepcopy(row.snapshot[k]) for k in ('map_id', 'lineup_id', 'name', 'description', 'side', 'category', 'document')}
    data.update(version=current, status='DRAFT')
    from app.models.team_lineup import TeamLineup
    if data['lineup_id']:
        lineup = db.session.get(TeamLineup, data['lineup_id'])
        if not lineup or lineup.team_id != team_id or (lineup.map_id is not None and lineup.map_id != data['map_id']):
            data['lineup_id'] = None
    return save(user, team_id, data, sid, historical_restore=True)


def delete(user, team_id, sid, version):
    item = get(user, team_id, sid, True)
    if item.version != version:
        raise ApiError('Strategy version conflict', status_code=409)
    from app.models.lineup_recommendation import LineupRecommendation
    db.session.query(LineupRecommendation).filter_by(strategy_id=sid).delete()
    db.session.query(StrategyRevision).filter_by(strategy_id=sid).delete()
    db.session.delete(item)
    commit()


def preparation(user, team_id, map_id, data=None):
    access(user, team_id, data is not None)
    get_map(map_id)
    item = db.session.query(TeamMapSetup).filter_by(team_id=team_id, map_id=map_id).first()
    if data is not None:
        validate.object_keys(data, ('lineup_id', 'notes', 'readiness', 'version'))
        if data.get('version') != (item.version if item else 0):
            raise ApiError('Preparation version conflict', status_code=409)
        lineup_for(team_id, map_id, data.get('lineup_id'))
        notes = validate.text(data.get('notes', ''))
        readiness = data.get('readiness', 'NOT_STARTED')
        if readiness not in ('NOT_STARTED', 'IN_PROGRESS', 'READY'):
            validate.invalid('Invalid preparation status')
        if not item:
            item = TeamMapSetup(team_id=team_id, map_id=map_id)
            db.session.add(item)
        item.lineup_id, item.notes, item.readiness = data.get('lineup_id'), notes, readiness
        commit()
    return {'map_id': map_id, 'lineup_id': item.lineup_id if item else None,
            'notes': item.notes if item else '', 'readiness': item.readiness if item else 'NOT_STARTED',
            'version': item.version if item else 0}
