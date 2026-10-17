"""Servicio de lineups (granadas y utilidades por mapa)."""

from app.errors import ApiError
from app.extensions import db
from app.models.lineup import GRENADE_TYPES, SIDES, Lineup
from app.models.map import Map
from app.validators import clean_str

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


def list_lineups(filters):
    """Devuelve la consulta de lineups aplicando filtros opcionales."""
    query = db.session.query(Lineup)

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


def get_lineup(lineup_id):
    lineup = db.session.get(Lineup, lineup_id)
    if lineup is None:
        raise ApiError("Lineup not found", status_code=404)
    return lineup


def create_lineup(data):
    errors, payload = _validate_payload(data)
    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)

    lineup = Lineup(**payload)
    db.session.add(lineup)
    db.session.commit()
    return lineup


def update_lineup(lineup_id, data):
    current = get_lineup(lineup_id)
    errors, payload = _validate_payload(data, partial=True)
    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)

    for key, value in payload.items():
        setattr(current, key, value)

    db.session.commit()
    return current


def delete_lineup(lineup_id):
    current = get_lineup(lineup_id)
    db.session.delete(current)
    db.session.commit()
