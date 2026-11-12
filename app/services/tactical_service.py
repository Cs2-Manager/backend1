from copy import deepcopy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from app.extensions import db
from app.errors import ApiError
from app.models.tactics import TeamStrategy, StrategyRevision, TeamMapSetup
from app.models.lineup import Lineup
from app.notifications.outbox import dispatch_event
from app.permissions.policies import can_read_tactics, can_manage_tactics
from app.realtime.events import record_activity
from app.services import team_lineup_service as rosters
from app.services.map_service import get_map
from app.services import tactical_validation as validate
from app.serializers.tactics import strategy_payload


def _dispatch(event):
    """Entrega best-effort después del commit; nunca revierte la operación."""
    if event:
        dispatch_event(event["event_id"])


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


def _starter_ids(lineup):
    return {player.user_id for player in lineup.players if player.is_starter}


def _lineup_members(team, item):
    members = {m.user_id for m in team.members}
    if not item.lineup_id:
        return set()
    lineup = rosters._get_lineup(item.team_id, item.lineup_id)
    members &= _starter_ids(lineup)
    if lineup.map_id is not None and lineup.map_id != item.map_id:
        return set()
    return members


def _visible_grenades(user, team_id, map_id):
    from app.services.lineup_service import visible_query

    query = (
        visible_query(user)
        .filter_by(map_id=map_id)
        .filter(
            db.or_(
                Lineup.team_id == team_id,
                Lineup.visibility == 'PUBLIC',
            )
        )
    )
    return {grenade.id for grenade in query}


def payload(user, item):
    team, role = access(user, item.team_id)
    return strategy_payload(
        item,
        member_ids=_lineup_members(team, item),
        grenade_ids=_visible_grenades(user, item.team_id, item.map_id),
        can_edit=can_manage_tactics(user, role),
    )


_LISTING_FILTERS = ('map_id', 'side', 'category', 'status')


def _listing_query(team_id, filters):
    query = db.session.query(TeamStrategy).filter_by(team_id=team_id)
    for field in _LISTING_FILTERS:
        if filters.get(field):
            query = query.filter(getattr(TeamStrategy, field) == filters[field])
    if filters.get('q'):
        query = query.filter(
            TeamStrategy.name.icontains(filters['q'][:160], autoescape=True)
        )
    return query.order_by(TeamStrategy.updated_at.desc()).limit(200).all()


def _roster_map(items):
    from app.models.team_lineup import TeamLineupPlayer

    lineup_ids = [s.lineup_id for s in items if s.lineup_id]
    entries = (
        db.session.query(TeamLineupPlayer)
        .filter(
            TeamLineupPlayer.lineup_id.in_(lineup_ids),
            TeamLineupPlayer.is_starter.is_(True),
        )
        .all()
    )
    rosters_by_id = {}
    for entry in entries:
        rosters_by_id.setdefault(entry.lineup_id, set()).add(entry.user_id)
    return rosters_by_id


def _grenade_map(user, team_id, items):
    from app.services.lineup_service import visible_query

    query = (
        visible_query(user)
        .filter(Lineup.map_id.in_([s.map_id for s in items]))
        .filter(
            db.or_(Lineup.team_id == team_id, Lineup.visibility == 'PUBLIC')
        )
    )
    grenade_map = {}
    for grenade in query:
        grenade_map.setdefault(grenade.map_id, set()).add(grenade.id)
    return grenade_map


def _listing_payloads(items, members, rosters_by_id, grenade_map, can_edit):
    return [
        strategy_payload(
            item,
            member_ids=members & rosters_by_id.get(item.lineup_id, set()),
            grenade_ids=grenade_map.get(item.map_id, set()),
            can_edit=can_edit,
        )
        for item in items
    ]


def listing(user, team_id, filters):
    team, role = access(user, team_id)
    items = _listing_query(team_id, filters)
    rosters_by_id = _roster_map(items)
    members = {member.user_id for member in team.members}
    grenade_map = _grenade_map(user, team_id, items)
    return _listing_payloads(
        items,
        members,
        rosters_by_id,
        grenade_map,
        can_manage_tactics(user, role),
    )


def lineup_for(team_id, map_id, lineup_id):
    if lineup_id is None:
        return None
    if type(lineup_id) is not int:
        validate.invalid('Invalid lineup identifier')
    lineup = rosters._get_lineup(team_id, lineup_id)
    if lineup.map_id is not None and lineup.map_id != map_id:
        validate.invalid('Lineup belongs to another map')
    return lineup


_SAVE_KEYS = (
    'map_id',
    'lineup_id',
    'name',
    'description',
    'side',
    'category',
    'status',
    'version',
    'document',
)
_STRATEGY_FIELDS = (
    ('name', '', 160),
    ('description', '', 4000),
    ('side', 'T', 2),
    ('category', 'Default', 30),
    ('status', 'DRAFT', 12),
)
_EMPTY_DOCUMENT = {
    'schema_version': 1,
    'elements': [],
    'steps': [],
    'assignments': [],
    'notes': '',
}


def _check_strategy_version(item, version):
    if item and version != item.version:
        raise ApiError('Strategy version conflict', status_code=409)


def _resolve_map_id(data, item):
    mid = data.get('map_id', item.map_id if item else None)
    if type(mid) is not int:
        validate.invalid('Invalid map')
    get_map(mid)
    return mid


def _save_players(team, lineup):
    if lineup is None:
        return set()
    players = {p.user_id for p in lineup.players if p.is_starter}
    return players & {member.user_id for member in team.members}


def _validate_strategy_metadata(values):
    valid = (
        values['name']
        and values['side'] in ('CT', 'T')
        and values['category'] in validate.CATEGORIES
        and values['status'] in ('DRAFT', 'PUBLISHED', 'ARCHIVED')
    )
    if not valid:
        validate.invalid('Invalid strategy metadata')


def _strategy_values(data, item):
    values = {}
    for field, default, maximum in _STRATEGY_FIELDS:
        source = data.get(field, getattr(item, field, default))
        values[field] = validate.text(source, maximum)
    _validate_strategy_metadata(values)
    return values


def _document_source(data, item):
    if 'document' in data:
        return data['document']
    if item is not None:
        return item.document
    return _EMPTY_DOCUMENT


def _element_users(raw):
    return {
        element['user_id']
        for element in raw.get('elements', [])
        if element.get('user_id')
    }


def _assignment_users(raw):
    return {assignment['user_id'] for assignment in raw.get('assignments', [])}


def _step_users(raw):
    users = set()
    for step in raw.get('steps', []):
        users.update(step.get('user_ids', []))
    return users


def _referenced_grenades(raw):
    grenades = set()
    entries = raw.get('assignments', []) + raw.get('steps', [])
    for entry in entries:
        grenades.update(entry.get('grenade_ids', []))
    return grenades


def _historical_references(raw, players, grenades):
    players |= _element_users(raw) | _assignment_users(raw) | _step_users(raw)
    grenades |= _referenced_grenades(raw)


def _record_revision(item, user):
    db.session.add(
        StrategyRevision(
            strategy_id=item.id,
            version=item.version,
            author_id=user.id,
            snapshot=strategy_payload(item),
        )
    )


def _apply_strategy_values(item, values, mid, lid):
    for field, value in values.items():
        setattr(item, field, value)
    item.map_id, item.lineup_id = mid, lid


def _save_activity(user, team_id, item, mid, created):
    event_name = (
        "team_strategy.created" if created else "team_strategy.updated"
    )
    verb = "creó" if created else "actualizó"
    return record_activity(
        team_id,
        user,
        event_name,
        f'{user.username} {verb} la estrategia "{item.name}".',
        resource_type="team_strategy",
        resource_id=item.id,
        path=f"/teams/{team_id}",
        metadata={
            "strategy_id": item.id,
            "strategy_name": item.name,
            "map_id": mid,
        },
    )


def _resolve_lineup_id(data, item):
    if 'lineup_id' in data:
        return data['lineup_id']
    if item is not None:
        return item.lineup_id
    return None


def save(user, team_id, data, strategy_id=None, *, historical_restore=False):
    team, _ = access(user, team_id, True)
    validate.object_keys(data, _SAVE_KEYS)
    item = get(user, team_id, strategy_id, True) if strategy_id else None
    _check_strategy_version(item, data.get('version'))
    mid = _resolve_map_id(data, item)
    lid = _resolve_lineup_id(data, item)
    lineup = lineup_for(team_id, mid, lid)
    players = _save_players(team, lineup)
    grenades = _visible_grenades(user, team_id, mid)
    values = _strategy_values(data, item)
    raw = _document_source(data, item)
    if historical_restore:
        # Only immutable server-side revisions may retain departed references.
        # The restored draft is explicitly marked for review by the serializer.
        _historical_references(raw, players, grenades)
    values['document'] = deepcopy(validate.document(raw, players, grenades))
    if item is None:
        item = TeamStrategy(team_id=team_id, map_id=mid, author_id=user.id)
        db.session.add(item)
    else:
        _record_revision(item, user)
    _apply_strategy_values(item, values, mid, lid)
    # Force a version increment even for identical saves (revision uniqueness).
    if strategy_id:
        item.version += 1
    activity = _save_activity(user, team_id, item, mid, strategy_id is None)
    commit()
    _dispatch(activity)
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


_SNAPSHOT_FIELDS = (
    'map_id',
    'lineup_id',
    'name',
    'description',
    'side',
    'category',
    'document',
)


def _snapshot_data(snapshot):
    return {key: deepcopy(snapshot[key]) for key in _SNAPSHOT_FIELDS}


def _valid_restore_lineup(data, team_id):
    from app.models.team_lineup import TeamLineup

    lineup = db.session.get(TeamLineup, data['lineup_id'])
    if not lineup:
        return False
    if lineup.team_id != team_id:
        return False
    return lineup.map_id is None or lineup.map_id == data['map_id']


def _keep_restore_lineup(data, team_id):
    if not data['lineup_id']:
        return
    if not _valid_restore_lineup(data, team_id):
        data['lineup_id'] = None


def restore(user, team_id, sid, version, current):
    get(user, team_id, sid, True)
    row = (
        db.session.query(StrategyRevision)
        .filter_by(strategy_id=sid, version=version)
        .first()
    )
    if not row:
        raise ApiError('Revision not found', status_code=404)
    data = _snapshot_data(row.snapshot)
    data.update(version=current, status='DRAFT')
    _keep_restore_lineup(data, team_id)
    return save(user, team_id, data, sid, historical_restore=True)


def delete(user, team_id, sid, version):
    item = get(user, team_id, sid, True)
    if item.version != version:
        raise ApiError('Strategy version conflict', status_code=409)
    from app.models.lineup_recommendation import LineupRecommendation
    db.session.query(LineupRecommendation).filter_by(strategy_id=sid).delete()
    db.session.query(StrategyRevision).filter_by(strategy_id=sid).delete()
    activity = record_activity(
        team_id,
        user,
        "team_strategy.deleted",
        f'{user.username} eliminó la estrategia "{item.name}".',
        resource_type="team_strategy",
        resource_id=item.id,
        path=f"/teams/{team_id}",
        metadata={"strategy_id": item.id, "strategy_name": item.name},
    )
    db.session.delete(item)
    commit()
    _dispatch(activity)


_READINESS_VALUES = ('NOT_STARTED', 'IN_PROGRESS', 'READY')
_PREPARATION_KEYS = ('lineup_id', 'notes', 'readiness', 'version')


def _readiness(data):
    readiness = data.get('readiness', 'NOT_STARTED')
    if readiness not in _READINESS_VALUES:
        validate.invalid('Invalid preparation status')
    return readiness


def _prepare_item(item, team_id, map_id):
    if item:
        return item
    item = TeamMapSetup(team_id=team_id, map_id=map_id)
    db.session.add(item)
    return item


def _preparation_update(team_id, map_id, data, item):
    validate.object_keys(data, _PREPARATION_KEYS)
    if data.get('version') != (item.version if item else 0):
        raise ApiError('Preparation version conflict', status_code=409)
    lineup_for(team_id, map_id, data.get('lineup_id'))
    notes = validate.text(data.get('notes', ''))
    readiness = _readiness(data)
    item = _prepare_item(item, team_id, map_id)
    item.lineup_id = data.get('lineup_id')
    item.notes = notes
    item.readiness = readiness
    commit()
    return item


def _preparation_response(item, map_id):
    return {
        'map_id': map_id,
        'lineup_id': item.lineup_id if item else None,
        'notes': item.notes if item else '',
        'readiness': item.readiness if item else 'NOT_STARTED',
        'version': item.version if item else 0,
    }


def preparation(user, team_id, map_id, data=None):
    access(user, team_id, data is not None)
    get_map(map_id)
    item = (
        db.session.query(TeamMapSetup)
        .filter_by(team_id=team_id, map_id=map_id)
        .first()
    )
    if data is not None:
        item = _preparation_update(team_id, map_id, data, item)
    return _preparation_response(item, map_id)
