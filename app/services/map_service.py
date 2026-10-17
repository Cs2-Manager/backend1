"""Servicio de mapas y sus zonas (callouts)."""

from app.errors import ApiError
from app.extensions import db
from app.models.map import Callout, Map
from app.validators import clean_str, parse_ratio

REQUIRED_MAP_FIELDS = ("name", "image_url")
REQUIRED_CALLOUT_FIELDS = ("zone_name", "x_ratio", "y_ratio")


def list_maps():
    """Devuelve la consulta de mapas ordenada por nombre."""
    return db.session.query(Map).order_by(Map.name)


def get_map(map_id):
    """Devuelve un mapa o lanza ApiError 404."""
    map_obj = db.session.get(Map, map_id)
    if map_obj is None:
        raise ApiError("Map not found", status_code=404)
    return map_obj


def create_map(data):
    errors = {}
    name = clean_str(data.get("name"))
    image_url = clean_str(data.get("image_url"))
    if not name:
        errors["name"] = "name is required"
    if not image_url:
        errors["image_url"] = "image_url is required"
    if errors:
        raise ApiError("Invalid map", status_code=400, fields=errors)

    if db.session.query(Map.id).filter_by(name=name).first():
        raise ApiError("Map name already exists", status_code=409)

    new_map = Map(
        name=name,
        image_url=image_url,
        active_pool=bool(data.get("active_pool", False)),
    )
    db.session.add(new_map)
    db.session.commit()
    return new_map


def update_map(map_id, data):
    current = get_map(map_id)

    if "name" in data:
        name = clean_str(data["name"])
        if not name:
            raise ApiError("name cannot be empty", status_code=400)
        existing = (
            db.session.query(Map.id)
            .filter(Map.name == name, Map.id != map_id)
            .first()
        )
        if existing:
            raise ApiError("Map name already exists", status_code=409)
        current.name = name
    if "image_url" in data:
        current.image_url = clean_str(data["image_url"])
    if "active_pool" in data:
        current.active_pool = bool(data["active_pool"])

    db.session.commit()
    return current


def delete_map(map_id):
    current = get_map(map_id)
    db.session.delete(current)
    db.session.commit()


def list_callouts(map_id):
    return get_map(map_id).callouts


def get_callout(map_id, callout_id):
    get_map(map_id)
    callout = db.session.get(Callout, callout_id)
    if callout is None or callout.map_id != map_id:
        raise ApiError("Callout not found", status_code=404)
    return callout


def create_callout(map_id, data):
    get_map(map_id)

    errors = {}
    zone_name = clean_str(data.get("zone_name"))
    if not zone_name:
        errors["zone_name"] = "zone_name is required"
    if data.get("x_ratio") is None:
        errors["x_ratio"] = "x_ratio is required"
    if data.get("y_ratio") is None:
        errors["y_ratio"] = "y_ratio is required"

    x_ratio = y_ratio = None
    if not errors:
        x_ratio = parse_ratio(data["x_ratio"], "x_ratio", errors)
        y_ratio = parse_ratio(data["y_ratio"], "y_ratio", errors)
    if errors:
        raise ApiError("Invalid callout", status_code=400, fields=errors)

    callout = Callout(
        map_id=map_id,
        zone_name=zone_name,
        x_ratio=x_ratio,
        y_ratio=y_ratio,
    )
    db.session.add(callout)
    db.session.commit()
    return callout


def update_callout(map_id, callout_id, data):
    callout = get_callout(map_id, callout_id)
    errors = {}

    if "zone_name" in data:
        zone_name = clean_str(data["zone_name"])
        if not zone_name:
            errors["zone_name"] = "zone_name cannot be empty"
        else:
            callout.zone_name = zone_name

    for key in ("x_ratio", "y_ratio"):
        if key in data:
            value = parse_ratio(data[key], key, errors)
            if value is not None:
                setattr(callout, key, value)

    if errors:
        raise ApiError("Invalid callout", status_code=400, fields=errors)

    db.session.commit()
    return callout


def delete_callout(map_id, callout_id):
    callout = get_callout(map_id, callout_id)
    db.session.delete(callout)
    db.session.commit()
