"""Servicio de lineups (granadas y utilidades por mapa)."""

from app.errors import ApiError
from app.extensions import db
from app.models.lineup import GRENADE_TYPES, SIDES, Lineup
from app.models.map import Map
from app.validators import clean_str
from app.models.lineup import GrenadeFavorite
from app.models.team import TeamMember
from app.permissions.policies import can_manage_grenade, is_admin
from app.permissions.roles import coerce_team_role
from app.services import tactical_validation as validate
from app.validators import parse_url

REQUIRED_FIELDS = ("map_id", "type", "side", "title", "video_url")


def _validate_payload(data, partial=False):
    """Valida un payload de lineup. Devuelve (errors, payload)."""
    errors = {}
    payload = {}

    for field in ("type", "side"):
        if partial and field not in data:
            continue
        value = clean_str(data.get(field))
        if not value:
            errors[field] = f"{field} is required"
        elif field == "type" and value not in GRENADE_TYPES:
            errors[field] = f"type must be one of {', '.join(GRENADE_TYPES)}"
        elif field == "side" and value not in SIDES:
            errors[field] = f"side must be one of {', '.join(SIDES)}"
        else:
            payload[field] = value

    if "map_id" in data:
        map_id = data["map_id"]
        if map_id is None or str(map_id).strip() == "":
            errors["map_id"] = "map_id is required"
        else:
            try:
                map_id = int(map_id)
            except (TypeError, ValueError):
                errors["map_id"] = "map_id must be an integer"
            else:
                if db.session.get(Map, map_id) is None:
                    errors["map_id"] = "Map not found"
                else:
                    payload["map_id"] = map_id
    elif not partial:
        errors["map_id"] = "map_id is required"

    for field in ("title", "description"):
        if partial and field not in data:
            continue
        value = clean_str(data.get(field))
        if field == "title" and not value:
            errors[field] = "title is required"
        else:
            payload[field] = value

    if not (partial and "video_url" not in data):
        from app.video import is_valid_video_url

        video_url = clean_str(data.get("video_url"))
        if not video_url:
            errors["video_url"] = "video_url is required"
        elif not is_valid_video_url(video_url):
            errors["video_url"] = "video_url must be a valid YouTube link"
        else:
            payload["video_url"] = video_url

    return errors, payload


def list_lineups(filters, viewer=None):
    """Devuelve la consulta de lineups aplicando filtros opcionales."""
    query = visible_query(viewer)
    if filters.get('q'):
        query = query.filter(Lineup.title.icontains(filters['q'][:160], autoescape=True))
    if filters.get('difficulty'):
        query = query.filter_by(difficulty=filters['difficulty'])

    map_id = filters.get("map_id")
    if map_id:
        if not str(map_id).isdigit():
            raise ApiError("map_id must be an integer", status_code=400)
        query = query.filter(Lineup.map_id == int(map_id))

    line_type = filters.get("type")
    if line_type:
        if line_type not in GRENADE_TYPES:
            raise ApiError(
                f"type must be one of {', '.join(GRENADE_TYPES)}",
                status_code=400,
            )
        query = query.filter(Lineup.type == line_type)

    side = filters.get("side")
    if side:
        if side not in SIDES:
            raise ApiError(
                f"side must be one of {', '.join(SIDES)}",
                status_code=400,
            )
        query = query.filter(Lineup.side == side)

    return query.order_by(Lineup.title)


def get_lineup(lineup_id, viewer=None):
    lineup = visible_query(viewer).filter(Lineup.id == lineup_id).first()
    if lineup is None:
        raise ApiError("Lineup not found", status_code=404)
    return lineup


def create_lineup(data, user=None):
    team_id = data.get('team_id')
    _manage(user, team_id)
    errors, payload = _validate_payload(data)
    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)

    payload.update(_extended(data, team_id, data.get('map_id')))
    scope = 'TEAM' if team_id else 'OFFICIAL'
    visibility = payload.pop('visibility', None) or ('TEAM' if team_id else 'PUBLIC')
    status = payload.pop('status', 'PUBLISHED')
    lineup = Lineup(
        **payload,
        team_id=team_id,
        author_id=user.id if user else None,
        scope=scope,
        visibility=visibility,
        version=1,
        status=status,
    )
    db.session.add(lineup)
    db.session.flush()
    from app.services.grenade_lineup_service import _add_revision
    _add_revision(lineup, user, 'CREATE', 'Lineup created')
    db.session.commit()
    return lineup


def update_lineup(lineup_id, data, user=None):
    current = get_lineup(lineup_id, user)
    _manage(user, current.team_id)
    errors, payload = _validate_payload(data, partial=True)
    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)

    payload.update(_extended(data, current.team_id, current.map_id))
    for key, value in payload.items():
        setattr(current, key, value)

    current.version += 1
    db.session.flush()
    from app.services.grenade_lineup_service import _add_revision
    _add_revision(current, user, 'UPDATE', 'Lineup updated')
    db.session.commit()
    return current


def delete_lineup(lineup_id, user=None):
    current = get_lineup(lineup_id, user)
    _manage(user, current.team_id)
    db.session.query(GrenadeFavorite).filter_by(lineup_id=lineup_id).delete()
    db.session.delete(current)
    db.session.commit()


def visible_query(user):
    """Lineups visibles según su scope.

    No existe bypass administrativo: un admin solo ve OFFICIAL publicadas y,
    si es autor o integrante, su propio contenido PERSONAL/TEAM.
    """
    query = db.session.query(Lineup)
    conditions = [db.and_(Lineup.scope == 'OFFICIAL', Lineup.status == 'PUBLISHED')]
    if user:
        conditions.append(
            db.and_(Lineup.scope == 'PERSONAL', Lineup.author_id == user.id)
        )
        teams = db.session.query(TeamMember.team_id).filter_by(user_id=user.id)
        conditions.append(
            db.and_(Lineup.scope == 'TEAM', Lineup.team_id.in_(teams))
        )
    return query.filter(db.or_(*conditions))


def _manage(user, team_id):
    role = None
    if team_id is not None:
        if type(team_id) is not int:
            validate.invalid('Invalid team identifier')
        from app.services.team_lineup_service import _get_team, _role_for
        role = _role_for(user, _get_team(team_id))
    if not can_manage_grenade(user, team_id=team_id, team_role=role):
        raise ApiError('You cannot manage this grenade', status_code=403)


def _extended(data, team_id, map_id=None):
    result = {}
    for field in ('launch_zone', 'impact_zone'):
        if field in data:
            result[field] = validate.text(data[field], 120)
    for field, allowed in [('difficulty', ('EASY', 'MEDIUM', 'HARD')), ('status', ('DRAFT', 'PUBLISHED', 'ARCHIVED')), ('visibility', ('PUBLIC', 'TEAM'))]:
        if field in data:
            if data[field] not in allowed or (field == 'visibility' and data[field] == 'TEAM' and not team_id):
                validate.invalid('Invalid grenade ' + field)
            result[field] = data[field]
    for field in ('position', 'launch_position', 'impact_position'):
        if field in data:
            result[field] = validate.point(data[field]) if data[field] is not None else None
    if 'impact_position' not in result and 'position' in result:
        result['impact_position'] = result['position']
    for field, maximum in [('throw_type', 30), ('instructions', 4000), ('notes', 4000), ('game_version', 40)]:
        if field in data:
            result[field] = validate.text(data.get(field) or '', maximum)
    if 'tags' in data:
        tags = data['tags']
        if tags is None:
            result['tags'] = []
        elif not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(tag, str) or len(tag) > 30 for tag in tags):
            validate.invalid('Invalid lineup tags')
        else:
            result['tags'] = [tag.strip() for tag in tags if tag.strip()]
    for field in ('launch_callout_id', 'impact_callout_id'):
        if field in data:
            value = data[field]
            if value is None:
                result[field] = None
            elif type(value) is not int:
                validate.invalid('Invalid callout identifier')
            else:
                from app.models.map import Callout
                callout = db.session.get(Callout, value)
                if map_id is None:
                    validate.invalid('map_id is required to assign callouts')
                if callout is None or callout.map_id != int(map_id):
                    validate.invalid('Callout does not belong to the selected map')
                result[field] = value
    if 'image_url' in data:
        from app.services.media_validation import demonstration_url
        result['image_url'] = demonstration_url(data['image_url'])
    if 'responsible_id' in data:
        uid = data['responsible_id']
        if uid is not None and (type(uid) is not int or not team_id or not db.session.query(TeamMember.id).filter_by(team_id=team_id, user_id=uid).first()):
            validate.invalid('Responsible player must belong to the team')
        result['responsible_id'] = uid
    return result


def duplicate(lineup_id, user):
    item = get_lineup(lineup_id, user)
    _manage(user, item.team_id)
    data = {k: getattr(item, k) for k in (
        'map_id', 'type', 'side', 'title', 'description', 'video_url', 'team_id',
        'visibility', 'difficulty', 'launch_zone', 'impact_zone', 'position',
        'image_url', 'responsible_id', 'launch_position', 'impact_position',
        'launch_callout_id', 'impact_callout_id', 'throw_type', 'instructions',
        'notes', 'tags', 'game_version',
    )}
    data['title'] = item.title[:150] + ' (copy)'
    return create_lineup(data, user)


def favorite(lineup_id, user, enabled):
    get_lineup(lineup_id, user)
    current = db.session.get(GrenadeFavorite, (user.id, lineup_id))
    if enabled and current is None:
        db.session.add(GrenadeFavorite(user_id=user.id, lineup_id=lineup_id))
    elif not enabled and current:
        db.session.delete(current)
    from app.services.tactical_service import commit
    commit()


def favorites(user):
    return [g.id for g in visible_query(user).join(GrenadeFavorite, GrenadeFavorite.lineup_id == Lineup.id).filter(GrenadeFavorite.user_id == user.id)]
