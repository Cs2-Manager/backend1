"""Servicio de mapas de la Steam Workshop."""

from app.errors import ApiError
from app.extensions import db
from app.models.workshop_map import WORKSHOP_CATEGORIES, WorkshopMap
from app.validators import clean_str

REQUIRED_FIELDS = ("title", "category", "image_url", "workshop_url")


def list_workshop_maps(category=None):
    query = db.session.query(WorkshopMap)
    if category:
        if category not in WORKSHOP_CATEGORIES:
            raise ApiError(
                f"category must be one of {', '.join(WORKSHOP_CATEGORIES)}",
                status_code=400,
            )
        query = query.filter(WorkshopMap.category == category)
    return query.order_by(WorkshopMap.title)


def get_workshop_map(workshop_map_id):
    item = db.session.get(WorkshopMap, workshop_map_id)
    if item is None:
        raise ApiError("Workshop map not found", status_code=404)
    return item


def _validate_payload(data, partial=False):
    """Valida un payload de workshop map. Devuelve (errors, payload)."""
    errors = {}
    payload = {}

    if "category" in data or not partial:
        category = clean_str(data.get("category"))
        if not category:
            errors["category"] = "category is required"
        elif category not in WORKSHOP_CATEGORIES:
            errors["category"] = (
                f"category must be one of {', '.join(WORKSHOP_CATEGORIES)}"
            )
        else:
            payload["category"] = category

    for field in ("title", "image_url", "workshop_url"):
        if partial and field not in data:
            continue
        value = clean_str(data.get(field))
        if not value:
            errors[field] = f"{field} is required"
        else:
            payload[field] = value

    if partial and "description" not in data:
        return errors, payload
    payload["description"] = clean_str(data.get("description"))

    return errors, payload


def create_workshop_map(data):
    errors, payload = _validate_payload(data)
    if errors:
        raise ApiError("Invalid workshop map", status_code=400, fields=errors)

    item = WorkshopMap(**payload)
    db.session.add(item)
    db.session.commit()
    return item


def update_workshop_map(workshop_map_id, data):
    current = get_workshop_map(workshop_map_id)
    errors, payload = _validate_payload(data, partial=True)
    if errors:
        raise ApiError("Invalid workshop map", status_code=400, fields=errors)

    for key, value in payload.items():
        setattr(current, key, value)

    db.session.commit()
    return current


def delete_workshop_map(workshop_map_id):
    current = get_workshop_map(workshop_map_id)
    db.session.delete(current)
    db.session.commit()
