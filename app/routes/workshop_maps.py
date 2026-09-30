from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.workshop_map import WORKSHOP_CATEGORIES, WorkshopMap

workshop_maps_bp = Blueprint("workshop_maps", __name__, url_prefix="/api/workshop-maps")

REQUIRED_FIELDS = ("title", "category", "image_url", "workshop_url")


def get_workshop_map_or_404(workshop_map_id):
    return db.session.get(WorkshopMap, workshop_map_id) or (
        (jsonify({"error": "Workshop map not found"}), 404)
    )


def validate_payload(data, partial=False):
    """Validate a workshop map payload. Returns (errors, payload)."""
    errors = {}
    payload = {}

    if "category" in data or not partial:
        category = (data.get("category") or "").strip()
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
        value = (data.get(field) or "").strip()
        if not value:
            errors[field] = f"{field} is required"
        else:
            payload[field] = value

    if partial and "description" not in data:
        return errors, payload
    payload["description"] = (data.get("description") or "").strip()

    return errors, payload


@workshop_maps_bp.route("", methods=["GET"])
def list_workshop_maps():
    query = db.session.query(WorkshopMap)

    category = request.args.get("category")
    if category:
        if category not in WORKSHOP_CATEGORIES:
            return (
                jsonify(
                    {
                        "error": f"category must be one of "
                        f"{', '.join(WORKSHOP_CATEGORIES)}"
                    }
                ),
                400,
            )
        query = query.filter(WorkshopMap.category == category)

    items = query.order_by(WorkshopMap.title).all()
    return jsonify({"workshop_maps": [w.to_dict() for w in items]}), 200


@workshop_maps_bp.route("", methods=["POST"])
def create_workshop_map():
    data = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return (
            jsonify({"error": "Missing required fields", "fields": missing}),
            400,
        )

    errors, payload = validate_payload(data)
    if errors:
        return jsonify({"error": "Invalid workshop map", "fields": errors}), 400

    workshop_map = WorkshopMap(**payload)
    db.session.add(workshop_map)
    db.session.commit()
    return jsonify({"workshop_map": workshop_map.to_dict()}), 201


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["GET"])
def get_workshop_map(workshop_map_id):
    result = get_workshop_map_or_404(workshop_map_id)
    if isinstance(result, tuple):
        return result
    return jsonify({"workshop_map": result.to_dict()}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["PUT"])
def update_workshop_map(workshop_map_id):
    result = get_workshop_map_or_404(workshop_map_id)
    if isinstance(result, tuple):
        return result
    current = result

    data = request.get_json(silent=True) or {}
    errors, payload = validate_payload(data, partial=True)
    if errors:
        return jsonify({"error": "Invalid workshop map", "fields": errors}), 400

    for key, value in payload.items():
        setattr(current, key, value)

    db.session.commit()
    return jsonify({"workshop_map": current.to_dict()}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["DELETE"])
def delete_workshop_map(workshop_map_id):
    result = get_workshop_map_or_404(workshop_map_id)
    if isinstance(result, tuple):
        return result
    db.session.delete(result)
    db.session.commit()
    return jsonify({"message": "Workshop map deleted successfully"}), 200
