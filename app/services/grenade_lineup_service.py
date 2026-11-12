"""Servicio de lineups de granadas: oficiales, personales y de equipo.

Reglas de privacidad (verificadas en cada operación):

- OFFICIAL: lectura pública solo si está PUBLISHED; escritura solo admin.
- PERSONAL: lectura y escritura exclusivas del autor. Ningún administrador
  obtiene acceso por `is_admin`.
- TEAM: lectura y edición exclusivas de integrantes actuales del equipo.

Las propuestas guardan un snapshot inmutable. Aprobar una propuesta crea una
lineup TEAM independiente de la copia personal original.
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.errors import ApiError
from app.extensions import db
from app.models.grenade_lineup import (
    PROPOSAL_STATUSES,
    GrenadeLineupMedia,
    GrenadeLineupRevision,
    TeamGrenadeLineupProposal,
)
from app.models.lineup import (
    GRENADE_TYPES,
    LINEUP_DIFFICULTIES,
    LINEUP_GRENADE_TYPES,
    LINEUP_SIDES,
    THROW_TYPES,
    GrenadeFavorite,
    Lineup,
)
from app.models.map import Callout, Map
from app.models.team import Team, TeamMember
from app.permissions.policies import (
    can_decide_team_grenade_proposal,
    can_edit_personal_grenade,
    can_edit_team_grenade,
    can_manage_official_grenade,
    can_propose_grenade,
    can_read_personal_grenade,
    can_read_team_grenade,
    can_view_team_grenade_proposals,
    is_admin,
    is_owner,
)
from app.permissions.roles import coerce_team_role
from app.notifications.outbox import dispatch_event, queue_event
from app.realtime.events import (
    build_proposal_approved,
    build_proposal_created,
    build_proposal_rejected,
    record_activity,
)
from app.serializers.lineups import (
    serialize_grenade_lineup,
    serialize_grenade_media,
    serialize_grenade_proposal,
    serialize_grenade_revision,
)
from app.services import tactical_validation as validate
from app.services.media_validation import demonstration_url, public_https_url
from app.validators import clean_str
from app.video import is_valid_video_url

TYPE_ALIASES = {
    "SMOKE": ("Smoke",),
    "FLASH": ("Flash", "Flashbang"),
    "MOLOTOV": ("Molotov",),
    "INCENDIARY": ("Incendiary",),
    "HE": ("HE", "HE Grenade"),
    "DECOY": ("Decoy",),
}
SPECIAL_TYPE_ALIASES = {"FLASHBANG": "FLASH", "HE GRENADE": "HE"}

CONTENT_FIELDS = (
    "map_id",
    "type",
    "side",
    "title",
    "description",
    "video_url",
    "image_url",
    "difficulty",
    "status",
    "visibility",
    "launch_zone",
    "impact_zone",
    "launch_position",
    "impact_position",
    "position",
    "launch_callout_id",
    "impact_callout_id",
    "throw_type",
    "instructions",
    "notes",
    "tags",
    "game_version",
)


def _utcnow():
    return datetime.now(timezone.utc)


def _options():
    return (
        selectinload(Lineup.media),
        selectinload(Lineup.author),
        selectinload(Lineup.map),
        selectinload(Lineup.team),
    )


def _commit():
    try:
        db.session.commit()
    except (IntegrityError, StaleDataError) as error:
        db.session.rollback()
        raise ApiError(
            "Resource changed concurrently; reload before saving",
            status_code=409,
        ) from error


def _dispatch(event):
    """Entrega best-effort después del commit; nunca revierte la operación."""
    if event:
        dispatch_event(event["event_id"])


def _canonical_type(value):
    key = clean_str(value)
    upper = key.upper()
    if upper in TYPE_ALIASES:
        return upper
    for canonical, aliases in TYPE_ALIASES.items():
        if key in aliases:
            return canonical
    return SPECIAL_TYPE_ALIASES.get(upper)


def _canonical_side(value):
    key = clean_str(value).upper()
    if key == "TR":
        key = "T"
    return key if key in LINEUP_SIDES else None


def _type_filter_values(value):
    canonical = _canonical_type(value)
    if canonical is None:
        raise ApiError("Invalid grenade type", status_code=400)
    return [canonical, *TYPE_ALIASES[canonical]]


def _role_for(user, team_id):
    if user is None or team_id is None:
        return None
    membership = (
        db.session.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
        .first()
    )
    return coerce_team_role(membership.role) if membership else None


def _require_member(user, team_id, *, message="You are not a member of this team"):
    if user is None:
        raise ApiError(message, status_code=403)
    role = _role_for(user, team_id)
    if role is None:
        raise ApiError(message, status_code=403)
    return role


def _get_team(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        raise ApiError("Team not found", status_code=404)
    return team


def _ensure_map_accepts_lineups(map_obj, user, allow_archived):
    if allow_archived or map_obj.status != "ARCHIVED" or is_admin(user):
        return
    raise ApiError(
        "This map is archived and cannot receive new lineups",
        status_code=409,
    )


def _get_map(map_id, *, user=None, allow_archived=True):
    try:
        map_id = int(map_id)
    except (TypeError, ValueError) as error:
        raise ApiError(
            "Invalid lineup", status_code=400, fields={"map_id": "map_id must be an integer"}
        ) from error
    map_obj = db.session.get(Map, map_id)
    if map_obj is None:
        raise ApiError(
            "Invalid lineup", status_code=400, fields={"map_id": "Map not found"}
        )
    _ensure_map_accepts_lineups(map_obj, user, allow_archived)
    return map_obj


def _point(value, field, errors):
    try:
        return validate.point(value)
    except ApiError as error:
        errors[field] = str(error)
        return None


def _text_field(data, field, errors, maximum=4000):
    value = data[field]
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        errors[field] = f"{field} must be text up to {maximum} characters"
        return None
    return value.strip()


def _callout_id(data, field, map_obj, errors):
    value = data[field]
    if value in (None, ""):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        errors[field] = f"{field} must be an integer"
        return None
    callout = db.session.get(Callout, value)
    if callout is None or callout.map_id != map_obj.id:
        errors[field] = f"{field} does not belong to the selected map"
        return None
    return value


def _safe_media_url(value, index, errors):
    try:
        return public_https_url(value, field="url")
    except ApiError as error:
        errors["media"] = f"media[{index}]: {error.message}"
        return None


def _safe_thumbnail(value, index, errors):
    if not value:
        return None
    try:
        return demonstration_url(value)
    except ApiError as error:
        errors["media"] = f"media[{index}]: {error.message}"
        return False


def _media_item(entry, index, errors):
    if not isinstance(entry, dict):
        errors["media"] = "each media item must be an object"
        return None
    kind = clean_str(entry.get("kind", "IMAGE")).upper()
    if kind not in ("IMAGE", "VIDEO"):
        errors["media"] = "media kind must be IMAGE or VIDEO"
        return None
    url = _safe_media_url(entry.get("url"), index, errors)
    if url is None:
        return None
    thumbnail = _safe_thumbnail(entry.get("thumbnail_url"), index, errors)
    if thumbnail is False:
        return None
    return {
        "kind": kind,
        "url": url,
        "thumbnail_url": thumbnail,
        "position": index,
    }


def _valid_media_list(raw, errors):
    if raw is None:
        return None
    if isinstance(raw, list) and len(raw) <= 20:
        return raw
    errors["media"] = "media must be a list of at most 20 items"
    return None


def _media_items(data, errors):
    raw = _valid_media_list(data.get("media"), errors)
    if raw is None:
        return None
    items = []
    for index, entry in enumerate(raw):
        item = _media_item(entry, index, errors)
        if item is None:
            return None
        items.append(item)
    return items


def _validate_map_id(data, partial, map_obj, values, errors):
    if partial and "map_id" not in data:
        return
    if "map_id" not in data:
        errors["map_id"] = "map_id is required"
    else:
        values["map_id"] = map_obj.id


def _validate_title(data, partial, values, errors):
    if partial and "title" not in data:
        return
    title = clean_str(data.get("title"))
    if not title:
        errors["title"] = "title is required"
    elif len(title) > 160:
        errors["title"] = "title must be up to 160 characters"
    else:
        values["title"] = title


def _validate_type(data, partial, values, errors):
    if partial and "type" not in data:
        return
    canonical = _canonical_type(data.get("type"))
    if canonical is None:
        errors["type"] = f"type must be one of {', '.join(LINEUP_GRENADE_TYPES)}"
    else:
        values["type"] = canonical


def _validate_side(data, partial, values, errors):
    if partial and "side" not in data:
        return
    side = _canonical_side(data.get("side"))
    if side is None:
        errors["side"] = f"side must be one of {', '.join(LINEUP_SIDES)}"
    else:
        values["side"] = side


def _validate_identity(data, partial, map_obj, values, errors):
    _validate_map_id(data, partial, map_obj, values, errors)
    _validate_title(data, partial, values, errors)


def _validate_classification(data, partial, values, errors):
    _validate_type(data, partial, values, errors)
    _validate_side(data, partial, values, errors)


def _validate_texts(data, values, errors):
    for field in ("description", "instructions", "notes"):
        if field in data:
            value = _text_field(data, field, errors)
            if value is not None:
                values[field] = value


def _validate_difficulty(data, values, errors):
    if "difficulty" not in data:
        return
    difficulty = clean_str(data["difficulty"]).upper()
    if difficulty not in LINEUP_DIFFICULTIES:
        errors["difficulty"] = (
            f"difficulty must be one of {', '.join(LINEUP_DIFFICULTIES)}"
        )
    else:
        values["difficulty"] = difficulty


def _validate_status(data, scope, values, errors):
    if "status" not in data:
        return
    status = clean_str(data["status"]).upper()
    if scope != "OFFICIAL":
        # El estado de publicación no aplica a PERSONAL/TEAM.
        return
    if status not in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        errors["status"] = "status must be DRAFT, PUBLISHED or ARCHIVED"
    else:
        values["status"] = status


def _validate_zones(data, values, errors):
    for field in ("launch_zone", "impact_zone"):
        if field in data:
            value = clean_str(data[field])
            if len(value) > 120:
                errors[field] = f"{field} must be up to 120 characters"
            else:
                values[field] = value


def _sync_position_compat(values):
    # Compatibilidad: `position` histórico representa el punto de impacto.
    if "position" in values and "impact_position" not in values:
        values["impact_position"] = values["position"]
    if "impact_position" in values and "position" not in values:
        values["position"] = values["impact_position"]


def _validate_positions(data, values, errors):
    for field in ("launch_position", "impact_position", "position"):
        if field in data:
            if data[field] is None:
                values[field] = None
            else:
                values[field] = _point(data[field], field, errors)
    _sync_position_compat(values)


def _validate_callouts(data, map_obj, values, errors):
    for field in ("launch_callout_id", "impact_callout_id"):
        if field in data:
            values[field] = _callout_id(data, field, map_obj, errors)


def _validate_throw_type(data, values, errors):
    if "throw_type" not in data:
        return
    throw_type = clean_str(data["throw_type"]).upper().replace(" ", "_")
    if throw_type and throw_type not in THROW_TYPES:
        # Se permiten técnicas personalizadas con nombre propio.
        if len(throw_type) > 30:
            errors["throw_type"] = "throw_type must be up to 30 characters"
        else:
            values["throw_type"] = throw_type
    else:
        values["throw_type"] = throw_type


def _invalid_tags(tags):
    return (
        not isinstance(tags, list)
        or len(tags) > 20
        or any(not isinstance(tag, str) or len(tag) > 30 for tag in tags)
    )


def _clean_tags(tags):
    return [tag.strip() for tag in tags if tag.strip()]


def _validate_tags(data, values, errors):
    if "tags" not in data:
        return
    tags = data["tags"]
    if tags is None:
        values["tags"] = []
    elif _invalid_tags(tags):
        errors["tags"] = "tags must be a list of up to 20 short strings"
    else:
        values["tags"] = _clean_tags(tags)


def _validate_game_version(data, values, errors):
    if "game_version" not in data:
        return
    value = clean_str(data["game_version"])
    if len(value) > 40:
        errors["game_version"] = "game_version must be up to 40 characters"
    else:
        values["game_version"] = value


def _validate_video_url(data, values, errors):
    if "video_url" not in data:
        return
    value = clean_str(data["video_url"])
    if not value:
        values["video_url"] = None
    elif not is_valid_video_url(value):
        errors["video_url"] = "video_url must be a valid YouTube link"
    else:
        values["video_url"] = value


def _validate_image_url(data, values, errors):
    if "image_url" not in data:
        return
    value = clean_str(data["image_url"])
    if not value:
        values["image_url"] = None
        return
    try:
        values["image_url"] = demonstration_url(value)
    except ApiError as error:
        errors["image_url"] = error.message


def _validate_responsible_member(value, scope, team_id, values, errors):
    try:
        value = int(value)
    except (TypeError, ValueError):
        errors["responsible_id"] = "responsible_id must be an integer"
        return
    if scope != "TEAM" or team_id is None:
        errors["responsible_id"] = "responsible_id only applies to team lineups"
    elif not db.session.query(TeamMember.id).filter_by(
        team_id=team_id, user_id=value
    ).first():
        errors["responsible_id"] = "Responsible player must belong to the team"
    else:
        values["responsible_id"] = value


def _validate_responsible(data, scope, team_id, values, errors):
    if "responsible_id" not in data:
        return
    value = data["responsible_id"]
    if value in (None, ""):
        values["responsible_id"] = None
    else:
        _validate_responsible_member(value, scope, team_id, values, errors)


def _validate(data, *, partial, map_obj, scope, team_id=None, existing=None):
    errors, values = {}, {}

    _validate_identity(data, partial, map_obj, values, errors)
    _validate_classification(data, partial, values, errors)
    _validate_texts(data, values, errors)
    _validate_difficulty(data, values, errors)
    _validate_status(data, scope, values, errors)
    _validate_zones(data, values, errors)
    _validate_positions(data, values, errors)
    _validate_callouts(data, map_obj, values, errors)
    _validate_throw_type(data, values, errors)
    _validate_tags(data, values, errors)
    _validate_game_version(data, values, errors)
    _validate_video_url(data, values, errors)
    _validate_image_url(data, values, errors)
    _validate_responsible(data, scope, team_id, values, errors)

    media = _media_items(data, errors) if "media" in data else None

    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)
    return values, media


def _content_snapshot(lineup):
    snapshot = {field: getattr(lineup, field) for field in CONTENT_FIELDS}
    snapshot["media"] = [
        {
            "kind": item.kind,
            "url": item.url,
            "thumbnail_url": item.thumbnail_url,
            "position": item.position,
        }
        for item in lineup.media
    ]
    return snapshot


def _add_revision(lineup, actor, action, summary=""):
    revision = GrenadeLineupRevision(
        lineup_id=lineup.id,
        version=lineup.version,
        actor_id=actor.id if actor else None,
        action=action,
        snapshot=_content_snapshot(lineup),
        change_summary=summary,
    )
    db.session.add(revision)
    return revision


def _replace_media(lineup, items):
    if items is None:
        return
    lineup.media.clear()
    db.session.flush()
    for entry in items:
        lineup.media.append(GrenadeLineupMedia(**entry))


def _visibility_for(scope):
    return {"OFFICIAL": "PUBLIC", "PERSONAL": "PRIVATE", "TEAM": "TEAM"}[scope]


def _official_access(lineup, viewer):
    if lineup.status == "PUBLISHED":
        return True
    return is_admin(viewer)


def _team_membership(lineup, viewer):
    return bool(
        viewer
        and lineup.team_id is not None
        and db.session.query(TeamMember.id)
        .filter_by(team_id=lineup.team_id, user_id=viewer.id)
        .first()
    )


def _access(lineup, viewer):
    """Devuelve (allowed, is_team_member). No concede bypass admin."""
    if lineup.scope == "OFFICIAL":
        return _official_access(lineup, viewer), False
    if lineup.scope == "PERSONAL":
        return can_read_personal_grenade(viewer, lineup.author_id), False
    if lineup.scope == "TEAM":
        member = _team_membership(lineup, viewer)
        return can_read_team_grenade(viewer, is_team_member=member), member
    return False, False


def _find(lineup_id, *, for_update=False):
    query = db.session.query(Lineup).options(*_options()).filter(Lineup.id == lineup_id)
    if for_update:
        query = query.with_for_update()
    return query.first()


def get_lineup(lineup_id, viewer):
    lineup = _find(lineup_id)
    if lineup is None:
        raise ApiError("Lineup not found", status_code=404)
    allowed, _ = _access(lineup, viewer)
    if not allowed:
        # 404 para no filtrar la existencia de contenido privado ajeno.
        raise ApiError("Lineup not found", status_code=404)
    return lineup


_EDIT_DENIED = {
    "OFFICIAL": "You cannot edit official lineups",
    "PERSONAL": "You cannot edit this personal lineup",
    "TEAM": "You cannot edit this team lineup",
}


def _can_edit_scope(lineup, user):
    if lineup.scope == "OFFICIAL":
        return can_manage_official_grenade(user)
    if lineup.scope == "PERSONAL":
        return can_edit_personal_grenade(user, lineup.author_id)
    if lineup.scope == "TEAM":
        role = _role_for(user, lineup.team_id)
        return can_edit_team_grenade(user, is_team_member=role is not None)
    return True


def _require_edit(lineup, user):
    if _can_edit_scope(lineup, user):
        return
    raise ApiError(_EDIT_DENIED[lineup.scope], status_code=403)


def serialize_for_viewer(lineup, viewer):
    _, member = _access(lineup, viewer)
    return serialize_grenade_lineup(lineup, viewer=viewer, is_team_member=member)


# --- Listados ---------------------------------------------------------------


def _apply_text_filter(query, filters):
    if not filters.get("q"):
        return query
    return query.filter(
        Lineup.title.icontains(str(filters["q"])[:160], autoescape=True)
    )


def _apply_type_filter(query, filters):
    if not filters.get("type"):
        return query
    values = [value.lower() for value in _type_filter_values(filters["type"])]
    return query.filter(func.lower(Lineup.type).in_(values))


def _apply_side_filter(query, filters):
    if not filters.get("side"):
        return query
    side = _canonical_side(filters["side"])
    if side is None:
        raise ApiError("Invalid side", status_code=400)
    aliases = ["TR", "T"] if side == "T" else [side]
    return query.filter(func.upper(Lineup.side).in_(aliases))


def _apply_difficulty_filter(query, filters):
    if not filters.get("difficulty"):
        return query
    difficulty = str(filters["difficulty"]).upper()
    if difficulty not in LINEUP_DIFFICULTIES:
        raise ApiError("Invalid difficulty", status_code=400)
    return query.filter(Lineup.difficulty == difficulty)


def _apply_map_filter(query, filters):
    if not filters.get("map_id"):
        return query
    try:
        map_id_value = int(filters["map_id"])
    except (TypeError, ValueError) as error:
        raise ApiError("Invalid map_id", status_code=400) from error
    return query.filter(Lineup.map_id == map_id_value)


def _apply_filters(query, filters):
    query = _apply_text_filter(query, filters)
    query = _apply_type_filter(query, filters)
    query = _apply_side_filter(query, filters)
    query = _apply_difficulty_filter(query, filters)
    return _apply_map_filter(query, filters)


_OFFICIAL_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED", "ALL")


def _official_status_filter(query, viewer, filters):
    status = filters.get("status")
    if not is_admin(viewer) or not status:
        return query.filter(Lineup.status == "PUBLISHED")
    status = str(status).upper()
    if status not in _OFFICIAL_STATUSES:
        raise ApiError("Invalid lineup status", status_code=400)
    if status == "ALL":
        return query
    return query.filter(Lineup.status == status)


def official_query(map_id=None, viewer=None, filters=None):
    filters = filters or {}
    query = db.session.query(Lineup).options(*_options()).filter(
        Lineup.scope == "OFFICIAL"
    )
    if map_id is not None:
        query = query.filter(Lineup.map_id == map_id)
    query = _official_status_filter(query, viewer, filters)
    return _apply_filters(query, filters)


def personal_query(user, filters=None):
    if user is None:
        raise ApiError("Authentication required", status_code=401)
    filters = filters or {}
    query = db.session.query(Lineup).options(*_options()).filter(
        Lineup.scope == "PERSONAL", Lineup.author_id == user.id
    )
    return _apply_filters(query, filters)


def team_query(team_id, viewer, filters=None):
    _require_member(viewer, team_id)
    filters = filters or {}
    query = db.session.query(Lineup).options(*_options()).filter(
        Lineup.scope == "TEAM", Lineup.team_id == team_id
    )
    if filters.get("include_archived") not in (True, "1", "true"):
        query = query.filter(Lineup.status != "ARCHIVED")
    return _apply_filters(query, filters)


def _resolve_team_id(viewer, filters):
    if viewer is None:
        raise ApiError("Authentication required", status_code=401)
    team_id = filters.get("team_id")
    if team_id in (None, ""):
        membership = db.session.query(TeamMember).filter_by(user_id=viewer.id).first()
        if membership is None:
            raise ApiError("You are not a member of a team", status_code=403)
        return membership.team_id
    try:
        return int(team_id)
    except (TypeError, ValueError) as error:
        raise ApiError("Invalid team_id", status_code=400) from error


def list_map_lineups(map_id, viewer, scope="OFFICIAL", filters=None):
    map_obj = _get_map(map_id, user=viewer)
    filters = filters or {}
    if scope == "OFFICIAL":
        return official_query(map_obj.id, viewer, filters), map_obj
    if scope == "PERSONAL":
        return personal_query(viewer, {**filters, "map_id": map_obj.id}), map_obj
    if scope == "TEAM":
        team_id = _resolve_team_id(viewer, filters)
        return team_query(team_id, viewer, {**filters, "map_id": map_obj.id}), map_obj
    raise ApiError("scope must be OFFICIAL, PERSONAL or TEAM", status_code=400)


# --- CRUD -------------------------------------------------------------------


def _resolve_create_scope(scope, user):
    scope = clean_str(scope).upper() or "PERSONAL"
    if scope not in ("OFFICIAL", "PERSONAL"):
        raise ApiError(
            "Team lineups are created by approving a proposal", status_code=400
        )
    if scope == "OFFICIAL" and not can_manage_official_grenade(user):
        raise ApiError("Administrator access required", status_code=403)
    return scope


def create_lineup(map_id, data, user, scope="PERSONAL"):
    if user is None:
        raise ApiError("Authentication required", status_code=401)
    scope = _resolve_create_scope(scope, user)

    map_obj = _get_map(map_id, user=user, allow_archived=False)
    values, media = _validate(
        data, partial=False, map_obj=map_obj, scope=scope
    )

    status = values.pop(
        "status", "DRAFT" if scope == "OFFICIAL" else "PUBLISHED"
    )
    lineup = Lineup(
        **values,
        scope=scope,
        visibility=_visibility_for(scope),
        status=status,
        team_id=None,
        author_id=user.id,
        version=1,
    )
    if scope == "PERSONAL":
        lineup.status = "PUBLISHED"
    db.session.add(lineup)
    db.session.flush()
    _replace_media(lineup, media)
    _add_revision(lineup, user, "CREATE", "Lineup created")
    _commit()
    db.session.refresh(lineup)
    return lineup


def _team_version_guard(lineup, lineup_id, data):
    expected = data.get("version")
    if expected is None:
        raise ApiError(
            "Invalid lineup",
            status_code=400,
            fields={"version": "version is required for team lineups"},
        )
    try:
        expected = int(expected)
    except (TypeError, ValueError) as error:
        raise ApiError(
            "Invalid lineup",
            status_code=400,
            fields={"version": "version must be an integer"},
        ) from error
    # Bloqueo optimista para PostgreSQL; no-op en SQLite.
    locked = (
        db.session.query(Lineup)
        .filter(Lineup.id == lineup_id)
        .with_for_update()
        .first()
    )
    lineup = locked or lineup
    if expected != lineup.version:
        raise ApiError(
            "Lineup version conflict; reload the latest version",
            status_code=409,
        )
    return lineup


def _optional_version_guard(lineup, data):
    if "version" not in data:
        return
    try:
        expected = int(data["version"])
    except (TypeError, ValueError):
        return
    if expected != lineup.version:
        raise ApiError(
            "Lineup version conflict; reload the latest version",
            status_code=409,
        )


def _update_map(lineup, data):
    map_obj = db.session.get(Map, data.get("map_id", lineup.map_id))
    if map_obj is None:
        raise ApiError(
            "Invalid lineup", status_code=400, fields={"map_id": "Map not found"}
        )
    return map_obj


def update_lineup(lineup_id, data, user):
    lineup = get_lineup(lineup_id, user)
    _require_edit(lineup, user)

    if lineup.scope == "TEAM":
        lineup = _team_version_guard(lineup, lineup_id, data)
    else:
        _optional_version_guard(lineup, data)

    map_obj = _update_map(lineup, data)
    values, media = _validate(
        data,
        partial=True,
        map_obj=map_obj,
        scope=lineup.scope,
        team_id=lineup.team_id,
        existing=lineup,
    )
    for field, value in values.items():
        setattr(lineup, field, value)
    _replace_media(lineup, media)
    lineup.version += 1
    lineup.visibility = _visibility_for(lineup.scope)
    db.session.flush()
    _add_revision(
        lineup,
        user,
        "UPDATE",
        clean_str(data.get("change_summary"))[:500] or "Lineup updated",
    )
    _commit()
    db.session.refresh(lineup)
    return lineup


def delete_lineup(lineup_id, user):
    lineup = get_lineup(lineup_id, user)
    _require_edit(lineup, user)
    db.session.query(GrenadeFavorite).filter_by(lineup_id=lineup_id).delete()
    db.session.delete(lineup)
    _commit()


def publish_official(lineup_id, user):
    lineup = get_lineup(lineup_id, user)
    if lineup.scope != "OFFICIAL":
        raise ApiError("Only official lineups can be published", status_code=400)
    if not can_manage_official_grenade(user):
        raise ApiError("Administrator access required", status_code=403)
    lineup.status = "PUBLISHED"
    lineup.version += 1
    db.session.flush()
    _add_revision(lineup, user, "PUBLISH", "Official lineup published")
    _commit()
    return lineup


def archive_official(lineup_id, user):
    lineup = get_lineup(lineup_id, user)
    if lineup.scope != "OFFICIAL":
        raise ApiError("Only official lineups can be archived", status_code=400)
    if not can_manage_official_grenade(user):
        raise ApiError("Administrator access required", status_code=403)
    lineup.status = "ARCHIVED"
    lineup.version += 1
    db.session.flush()
    _add_revision(lineup, user, "ARCHIVE", "Official lineup archived")
    _commit()
    return lineup


# --- Historial --------------------------------------------------------------


def list_revisions(lineup_id, user):
    lineup = get_lineup(lineup_id, user)
    rows = (
        db.session.query(GrenadeLineupRevision)
        .options(selectinload(GrenadeLineupRevision.actor))
        .filter(GrenadeLineupRevision.lineup_id == lineup.id)
        .order_by(GrenadeLineupRevision.version.desc())
        .all()
    )
    return lineup, [serialize_grenade_revision(row) for row in rows]


def _restore_version_guard(lineup, data):
    if lineup.scope != "TEAM":
        return
    expected = data.get("version")
    if expected is None:
        raise ApiError(
            "Invalid restore",
            status_code=400,
            fields={"version": "version is required for team lineups"},
        )
    try:
        expected = int(expected)
    except (TypeError, ValueError) as error:
        raise ApiError(
            "Invalid restore",
            status_code=400,
            fields={"version": "version must be an integer"},
        ) from error
    if expected != lineup.version:
        raise ApiError(
            "Lineup version conflict; reload the latest version",
            status_code=409,
        )


def restore_revision(lineup_id, version, data, user):
    lineup = get_lineup(lineup_id, user)
    _require_edit(lineup, user)
    _restore_version_guard(lineup, data)

    revision = (
        db.session.query(GrenadeLineupRevision)
        .filter_by(lineup_id=lineup.id, version=version)
        .first()
    )
    if revision is None:
        raise ApiError("Revision not found", status_code=404)

    snapshot = revision.snapshot or {}
    for field in CONTENT_FIELDS:
        if field in snapshot:
            setattr(lineup, field, snapshot[field])
    lineup.visibility = _visibility_for(lineup.scope)
    media = snapshot.get("media", [])
    _replace_media(lineup, media)
    lineup.version += 1
    db.session.flush()
    _add_revision(
        lineup, user, "RESTORE", f"Restored version {version}"
    )
    _commit()
    return lineup


# --- Propuestas -------------------------------------------------------------


def _get_proposal(proposal_id, *, for_update=False):
    query = db.session.query(TeamGrenadeLineupProposal).options(
        selectinload(TeamGrenadeLineupProposal.author),
        selectinload(TeamGrenadeLineupProposal.decided_by),
    )
    if for_update:
        query = query.with_for_update()
    return query.filter(TeamGrenadeLineupProposal.id == proposal_id).first()


def _proposal_access(proposal, viewer):
    if viewer is None:
        return False
    if is_owner(viewer, proposal.author_id):
        return True
    role = _role_for(viewer, proposal.team_id)
    return can_view_team_grenade_proposals(viewer, role)


def _proposal_team_id(user, data):
    membership = db.session.query(TeamMember).filter_by(user_id=user.id).first()
    if membership is None:
        raise ApiError("You must belong to a team to propose a lineup", status_code=400)
    requested_team = data.get("team_id")
    if requested_team in (None, ""):
        return membership.team_id
    try:
        requested_team = int(requested_team)
    except (TypeError, ValueError) as error:
        raise ApiError("Invalid team_id", status_code=400) from error
    if requested_team != membership.team_id:
        raise ApiError("You do not belong to that team", status_code=403)
    return membership.team_id


def _ensure_no_pending_proposal(team_id, lineup_id):
    pending = (
        db.session.query(TeamGrenadeLineupProposal.id)
        .filter_by(
            team_id=team_id,
            source_lineup_id=lineup_id,
            status="PENDING",
        )
        .first()
    )
    if pending:
        raise ApiError(
            "This lineup already has a pending proposal for the team",
            status_code=409,
        )


def propose(lineup_id, data, user):
    if user is None:
        raise ApiError("Authentication required", status_code=401)
    lineup = get_lineup(lineup_id, user)
    if lineup.scope != "PERSONAL" or not is_owner(user, lineup.author_id):
        raise ApiError("Only your personal lineups can be proposed", status_code=403)

    team_id = _proposal_team_id(user, data)

    if not can_propose_grenade(
        user, owner_id=lineup.author_id, is_team_member=True
    ):
        raise ApiError("You cannot propose this lineup", status_code=403)

    _ensure_no_pending_proposal(team_id, lineup.id)

    note = clean_str(data.get("note"))[:2000]
    proposal = TeamGrenadeLineupProposal(
        team_id=team_id,
        map_id=lineup.map_id,
        source_lineup_id=lineup.id,
        author_id=user.id,
        snapshot=_content_snapshot(lineup),
        status="PENDING",
        note=note,
    )
    db.session.add(proposal)
    db.session.flush()
    event = build_proposal_created(proposal, lineup, user)
    queue_event(event)
    activity = record_activity(
        team_id,
        user,
        "grenade.proposal.created",
        f'{user.username} propuso "{lineup.title}".',
        resource_type="grenade_proposal",
        resource_id=proposal.id,
        path=f"/teams/{team_id}",
        metadata={
            "proposal_id": proposal.id,
            "lineup_title": lineup.title,
            "lineup_type": lineup.type,
        },
    )
    _commit()
    _dispatch(event)
    _dispatch(activity)
    return proposal


def list_my_proposals(user, status=None):
    if user is None:
        raise ApiError("Authentication required", status_code=401)
    query = db.session.query(TeamGrenadeLineupProposal).options(
        selectinload(TeamGrenadeLineupProposal.author),
        selectinload(TeamGrenadeLineupProposal.decided_by),
    ).filter(TeamGrenadeLineupProposal.author_id == user.id)
    if status:
        status = _validate_proposal_status(status)
        query = query.filter(TeamGrenadeLineupProposal.status == status)
    return query.order_by(TeamGrenadeLineupProposal.created_at.desc())


def list_team_proposals(team_id, user, status=None):
    role = _require_member(user, team_id)
    if not can_view_team_grenade_proposals(user, role):
        raise ApiError(
            "Only the captain or coach can review team proposals",
            status_code=403,
        )
    query = db.session.query(TeamGrenadeLineupProposal).options(
        selectinload(TeamGrenadeLineupProposal.author),
        selectinload(TeamGrenadeLineupProposal.decided_by),
    ).filter(TeamGrenadeLineupProposal.team_id == team_id)
    if status:
        status = _validate_proposal_status(status)
        query = query.filter(TeamGrenadeLineupProposal.status == status)
    return query.order_by(TeamGrenadeLineupProposal.created_at.desc())


def get_proposal(proposal_id, user):
    proposal = _get_proposal(proposal_id)
    if proposal is None or not _proposal_access(proposal, user):
        raise ApiError("Proposal not found", status_code=404)
    return proposal


def _validate_proposal_status(status):
    status = clean_str(status).upper()
    if status not in PROPOSAL_STATUSES:
        raise ApiError("Invalid proposal status", status_code=400)
    return status


def _sanitize_proposal_callouts(values, map_id):
    for field in ("launch_callout_id", "impact_callout_id"):
        callout_id = values.get(field)
        if not callout_id:
            continue
        callout = db.session.get(Callout, callout_id)
        if callout is None or callout.map_id != map_id:
            values[field] = None


def _create_team_lineup_from_proposal(proposal, approver):
    snapshot = proposal.snapshot or {}
    values = {
        field: snapshot.get(field)
        for field in CONTENT_FIELDS
        if field in snapshot
    }
    values["map_id"] = proposal.map_id
    values["team_id"] = proposal.team_id
    values["scope"] = "TEAM"
    values["visibility"] = "TEAM"
    values["status"] = "PUBLISHED"
    values["author_id"] = proposal.author_id
    values["version"] = 1
    values["source_lineup_id"] = proposal.source_lineup_id
    values["source_proposal_id"] = proposal.id
    _sanitize_proposal_callouts(values, proposal.map_id)

    lineup = Lineup(**values)
    db.session.add(lineup)
    db.session.flush()
    for entry in snapshot.get("media", []):
        lineup.media.append(
            GrenadeLineupMedia(
                kind=entry.get("kind", "IMAGE"),
                url=entry["url"],
                thumbnail_url=entry.get("thumbnail_url"),
                position=entry.get("position", 0),
            )
        )
    _add_revision(
        lineup,
        approver,
        "APPROVED",
        f"Created from proposal #{proposal.id}",
    )
    return lineup


def _require_proposal_decider(user, proposal, action):
    role = _role_for(user, proposal.team_id)
    if can_decide_team_grenade_proposal(user, role):
        return
    raise ApiError(
        f"Only the captain or coach can {action} proposals", status_code=403
    )


def approve_proposal(proposal_id, user, data=None):
    proposal = _get_proposal(proposal_id, for_update=True)
    if proposal is None:
        raise ApiError("Proposal not found", status_code=404)
    _require_proposal_decider(user, proposal, "approve")
    if proposal.status != "PENDING":
        raise ApiError("Proposal is no longer pending", status_code=409)

    lineup = _create_team_lineup_from_proposal(proposal, user)
    proposal.status = "APPROVED"
    proposal.decided_by_id = user.id
    proposal.decided_at = _utcnow()
    proposal.approved_lineup_id = lineup.id
    if data and data.get("note"):
        proposal.note = clean_str(data["note"])[:2000]
    event = build_proposal_approved(proposal, user)
    queue_event(event)
    activity = record_activity(
        proposal.team_id,
        user,
        "grenade.proposal.approved",
        f'{user.username} aprobó la propuesta "{lineup.title}".',
        resource_type="team_lineup",
        resource_id=lineup.id,
        path=f"/teams/{proposal.team_id}/lineups/{lineup.id}",
        metadata={
            "proposal_id": proposal.id,
            "lineup_title": lineup.title,
            "lineup_type": lineup.type,
        },
    )
    _commit()
    db.session.refresh(proposal)
    _dispatch(event)
    _dispatch(activity)
    return proposal, lineup


def reject_proposal(proposal_id, user, data=None):
    proposal = _get_proposal(proposal_id, for_update=True)
    if proposal is None:
        raise ApiError("Proposal not found", status_code=404)
    role = _role_for(user, proposal.team_id)
    if not can_decide_team_grenade_proposal(user, role):
        raise ApiError(
            "Only the captain or coach can reject proposals", status_code=403
        )
    if proposal.status != "PENDING":
        raise ApiError("Proposal is no longer pending", status_code=409)

    proposal.status = "REJECTED"
    proposal.decided_by_id = user.id
    proposal.decided_at = _utcnow()
    proposal.rejection_reason = clean_str((data or {}).get("reason"))[:2000]
    event = build_proposal_rejected(proposal, user)
    queue_event(event)
    activity = record_activity(
        proposal.team_id,
        user,
        "grenade.proposal.rejected",
        f'{user.username} rechazó una propuesta de granada.',
        resource_type="grenade_proposal",
        resource_id=proposal.id,
        path=f"/teams/{proposal.team_id}",
        metadata={"proposal_id": proposal.id},
    )
    _commit()
    _dispatch(event)
    _dispatch(activity)
    return proposal


def cancel_proposal(proposal_id, user):
    proposal = _get_proposal(proposal_id, for_update=True)
    if proposal is None:
        raise ApiError("Proposal not found", status_code=404)
    if not is_owner(user, proposal.author_id):
        raise ApiError("Only the author can cancel this proposal", status_code=403)
    if proposal.status != "PENDING":
        raise ApiError("Proposal is no longer pending", status_code=409)
    proposal.status = "CANCELLED"
    proposal.decided_at = _utcnow()
    activity = record_activity(
        proposal.team_id,
        user,
        "grenade.proposal.cancelled",
        f"{user.username} canceló una propuesta de granada.",
        resource_type="grenade_proposal",
        resource_id=proposal.id,
        path=f"/teams/{proposal.team_id}",
        metadata={"proposal_id": proposal.id},
    )
    _commit()
    _dispatch(activity)
    return proposal


# --- Integración con equipos ------------------------------------------------


def cancel_pending_for_member(team_id, user_id):
    """Cancela propuestas pendientes del integrante que abandona el equipo."""
    now = _utcnow()
    rows = (
        db.session.query(TeamGrenadeLineupProposal)
        .filter_by(team_id=team_id, author_id=user_id, status="PENDING")
        .all()
    )
    for proposal in rows:
        proposal.status = "CANCELLED"
        proposal.decided_at = now
        proposal.rejection_reason = "Author left the team"
    return len(rows)


def archive_team_content(team_id, actor=None):
    """Preserva las lineups TEAM cuando el equipo deja de existir.

    Se desvinculan del equipo (team_id = NULL) y se marcan ARCHIVED. Al no
    existir equipo, la política de acceso las vuelve inaccesibles.
    """
    now = _utcnow()
    for proposal in (
        db.session.query(TeamGrenadeLineupProposal)
        .filter_by(team_id=team_id, status="PENDING")
        .all()
    ):
        proposal.status = "CANCELLED"
        proposal.decided_at = now
        proposal.rejection_reason = "Team dissolved"

    rows = (
        db.session.query(Lineup)
        .options(selectinload(Lineup.media))
        .filter_by(team_id=team_id, scope="TEAM")
        .all()
    )
    for lineup in rows:
        lineup.status = "ARCHIVED"
        lineup.team_id = None
        lineup.visibility = "PRIVATE"
        lineup.version += 1
        _add_revision(lineup, actor, "ARCHIVE", "Team dissolved")
    return len(rows)
