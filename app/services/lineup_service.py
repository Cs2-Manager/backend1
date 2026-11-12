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


_PAYLOAD_CHOICES = {"type": GRENADE_TYPES, "side": SIDES}


def _validate_choice(field, data, partial, errors, payload):
    if partial and field not in data:
        return
    value = clean_str(data.get(field))
    allowed = _PAYLOAD_CHOICES[field]
    if not value:
        errors[field] = f"{field} is required"
    elif value not in allowed:
        errors[field] = f"{field} must be one of {', '.join(allowed)}"
    else:
        payload[field] = value


def _parse_map_id(data, errors):
    map_id = data["map_id"]
    if map_id is None or str(map_id).strip() == "":
        errors["map_id"] = "map_id is required"
        return None
    try:
        return int(map_id)
    except (TypeError, ValueError):
        errors["map_id"] = "map_id must be an integer"
        return None


def _validate_map_id(data, partial, errors, payload):
    if "map_id" not in data:
        if not partial:
            errors["map_id"] = "map_id is required"
        return
    map_id = _parse_map_id(data, errors)
    if map_id is None:
        return
    if db.session.get(Map, map_id) is None:
        errors["map_id"] = "Map not found"
        return
    payload["map_id"] = map_id


def _validate_text(field, data, partial, errors, payload):
    if partial and field not in data:
        return
    value = clean_str(data.get(field))
    if field == "title" and not value:
        errors[field] = "title is required"
    else:
        payload[field] = value


def _validate_video_url(data, partial, errors, payload):
    if partial and "video_url" not in data:
        return
    from app.video import is_valid_video_url

    video_url = clean_str(data.get("video_url"))
    if not video_url:
        errors["video_url"] = "video_url is required"
    elif not is_valid_video_url(video_url):
        errors["video_url"] = "video_url must be a valid YouTube link"
    else:
        payload["video_url"] = video_url


def _validate_payload(data, partial=False):
    """Valida un payload de lineup. Devuelve (errors, payload)."""
    errors = {}
    payload = {}

    for field in _PAYLOAD_CHOICES:
        _validate_choice(field, data, partial, errors, payload)
    _validate_map_id(data, partial, errors, payload)
    for field in ("title", "description"):
        _validate_text(field, data, partial, errors, payload)
    _validate_video_url(data, partial, errors, payload)

    return errors, payload


def _filter_map_id(query, filters):
    map_id = filters.get("map_id")
    if not map_id:
        return query
    if not str(map_id).isdigit():
        raise ApiError("map_id must be an integer", status_code=400)
    return query.filter(Lineup.map_id == int(map_id))


def _filter_choice(query, filters, field, allowed):
    value = filters.get(field)
    if not value:
        return query
    if value not in allowed:
        raise ApiError(
            f"{field} must be one of {', '.join(allowed)}",
            status_code=400,
        )
    return query.filter(getattr(Lineup, field) == value)


def list_lineups(filters, viewer=None):
    """Devuelve la consulta de lineups aplicando filtros opcionales."""
    query = visible_query(viewer)
    if filters.get('q'):
        query = query.filter(Lineup.title.icontains(filters['q'][:160], autoescape=True))
    if filters.get('difficulty'):
        query = query.filter_by(difficulty=filters['difficulty'])

    query = _filter_map_id(query, filters)
    query = _filter_choice(query, filters, "type", GRENADE_TYPES)
    query = _filter_choice(query, filters, "side", SIDES)
    return query.order_by(Lineup.title)


def get_lineup(lineup_id, viewer=None):
    lineup = visible_query(viewer).filter(Lineup.id == lineup_id).first()
    if lineup is None:
        raise ApiError("Lineup not found", status_code=404)
    return lineup


def _lineup_scope_values(payload, team_id):
    scope = 'TEAM' if team_id else 'OFFICIAL'
    default_visibility = 'TEAM' if team_id else 'PUBLIC'
    visibility = payload.pop('visibility', None) or default_visibility
    status = payload.pop('status', 'PUBLISHED')
    return scope, visibility, status


def create_lineup(data, user=None):
    team_id = data.get('team_id')
    _manage(user, team_id)
    errors, payload = _validate_payload(data)
    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)

    payload.update(_extended(data, team_id, data.get('map_id')))
    scope, visibility, status = _lineup_scope_values(payload, team_id)
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


_EXTENDED_CHOICES = (
    ('difficulty', ('EASY', 'MEDIUM', 'HARD')),
    ('status', ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    ('visibility', ('PUBLIC', 'TEAM')),
)
_POINT_FIELDS = ('position', 'launch_position', 'impact_position')
_EXTENDED_TEXT_FIELDS = (
    ('throw_type', 30),
    ('instructions', 4000),
    ('notes', 4000),
    ('game_version', 40),
)
_CALLOUT_FIELDS = ('launch_callout_id', 'impact_callout_id')


def _invalid_choice(field, value, team_id):
    allowed = dict(_EXTENDED_CHOICES)[field]
    if value not in allowed:
        return True
    return field == 'visibility' and value == 'TEAM' and not team_id


def _extended_zones(data, result):
    for field in ('launch_zone', 'impact_zone'):
        if field in data:
            result[field] = validate.text(data[field], 120)


def _extended_choices(data, team_id, result):
    for field, _allowed in _EXTENDED_CHOICES:
        if field not in data:
            continue
        if _invalid_choice(field, data[field], team_id):
            validate.invalid('Invalid grenade ' + field)
        result[field] = data[field]


def _point_value(value):
    if value is None:
        return None
    return validate.point(value)


def _extended_positions(data, result):
    for field in _POINT_FIELDS:
        if field in data:
            result[field] = _point_value(data[field])
    if 'impact_position' not in result and 'position' in result:
        result['impact_position'] = result['position']


def _extended_texts(data, result):
    for field, maximum in _EXTENDED_TEXT_FIELDS:
        if field in data:
            result[field] = validate.text(data.get(field) or '', maximum)


def _tag_invalid(tag):
    return not isinstance(tag, str) or len(tag) > 30


def _tags_invalid(tags):
    if not isinstance(tags, list):
        return True
    if len(tags) > 20:
        return True
    return any(_tag_invalid(tag) for tag in tags)


def _clean_tags(tags):
    return [tag.strip() for tag in tags if tag.strip()]


def _extended_tags(data, result):
    if 'tags' not in data:
        return
    tags = data['tags']
    if tags is None:
        result['tags'] = []
        return
    if _tags_invalid(tags):
        validate.invalid('Invalid lineup tags')
    result['tags'] = _clean_tags(tags)


def _callout_matches(callout, map_id):
    if map_id is None:
        validate.invalid('map_id is required to assign callouts')
    return callout is not None and callout.map_id == int(map_id)


def _callout_value(value, map_id):
    if value is None:
        return None
    if type(value) is not int:
        validate.invalid('Invalid callout identifier')
    from app.models.map import Callout

    callout = db.session.get(Callout, value)
    if not _callout_matches(callout, map_id):
        validate.invalid('Callout does not belong to the selected map')
    return value


def _extended_callouts(data, map_id, result):
    for field in _CALLOUT_FIELDS:
        if field in data:
            result[field] = _callout_value(data[field], map_id)


def _extended_image(data, result):
    if 'image_url' not in data:
        return
    from app.services.media_validation import demonstration_url

    result['image_url'] = demonstration_url(data['image_url'])


def _responsible_invalid(uid, team_id):
    if uid is None:
        return False
    if type(uid) is not int or not team_id:
        return True
    query = db.session.query(TeamMember.id).filter_by(
        team_id=team_id, user_id=uid
    )
    return query.first() is None


def _extended_responsible(data, team_id, result):
    if 'responsible_id' not in data:
        return
    uid = data['responsible_id']
    if _responsible_invalid(uid, team_id):
        validate.invalid('Responsible player must belong to the team')
    result['responsible_id'] = uid


def _extended(data, team_id, map_id=None):
    result = {}
    _extended_zones(data, result)
    _extended_choices(data, team_id, result)
    _extended_positions(data, result)
    _extended_texts(data, result)
    _extended_tags(data, result)
    _extended_callouts(data, map_id, result)
    _extended_image(data, result)
    _extended_responsible(data, team_id, result)
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
