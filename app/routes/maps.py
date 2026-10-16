from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.map import Callout, Map

maps_bp = Blueprint("maps", __name__, url_prefix="/api/maps")

REQUIRED_MAP_FIELDS = ("name", "image_url")
REQUIRED_CALLOUT_FIELDS = ("zone_name", "x_ratio", "y_ratio")


def get_map_or_404(map_id):
    return db.session.get(Map, map_id) or ((jsonify({"error": "Map not found"}), 404))


def get_callout_of_map_or_404(map_id, callout_id):
    callout = db.session.get(Callout, callout_id)
    if callout is None or callout.map_id != map_id:
        return None, (jsonify({"error": "Callout not found"}), 404)
    return callout, None


@maps_bp.route("", methods=["GET"])
def list_maps():
    maps = db.session.query(Map).order_by(Map.name).all()
    return jsonify({"maps": [m.to_dict() for m in maps]}), 200


@maps_bp.route("", methods=["POST"])
def create_map():
    data = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_MAP_FIELDS if not (data.get(f) or "").strip()]
    if missing:
        return (
            jsonify({"error": "Missing required fields", "fields": missing}),
            400,
        )

    name = data["name"].strip()
    if db.session.query(Map.id).filter_by(name=name).first():
        return jsonify({"error": "Map name already exists"}), 409

    new_map = Map(
        name=name,
        image_url=data["image_url"].strip(),
        active_pool=bool(data.get("active_pool", False)),
    )
    db.session.add(new_map)
    db.session.commit()

    return jsonify({"map": new_map.to_dict()}), 201


@maps_bp.route("/<int:map_id>", methods=["GET"])
def get_map(map_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result
    return jsonify({"map": result.to_dict()}), 200


@maps_bp.route("/<int:map_id>", methods=["PUT"])
def update_map(map_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result
    current = result

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        existing = (
            db.session.query(Map.id).filter(Map.name == name, Map.id != map_id).first()
        )
        if existing:
            return jsonify({"error": "Map name already exists"}), 409
        current.name = name
    if "image_url" in data:
        current.image_url = (data["image_url"] or "").strip()
    if "active_pool" in data:
        current.active_pool = bool(data["active_pool"])

    db.session.commit()
    return jsonify({"map": current.to_dict()}), 200


@maps_bp.route("/<int:map_id>", methods=["DELETE"])
def delete_map(map_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result
    db.session.delete(result)
    db.session.commit()
    return jsonify({"message": "Map deleted successfully"}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["GET"])
def list_callouts(map_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result
    return jsonify({"callouts": [c.to_dict() for c in result.callouts]}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["POST"])
def create_callout(map_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result

    data = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_CALLOUT_FIELDS if data.get(f) is None]
    if missing:
        return (
            jsonify({"error": "Missing required fields", "fields": missing}),
            400,
        )

    try:
        x_ratio = float(data["x_ratio"])
        y_ratio = float(data["y_ratio"])
    except (TypeError, ValueError):
        return jsonify({"error": "x_ratio and y_ratio must be numeric"}), 400

    if not 0 <= x_ratio <= 1 or not 0 <= y_ratio <= 1:
        return (
            jsonify({"error": "x_ratio and y_ratio must be between 0 and 1"}),
            400,
        )

    callout = Callout(
        map_id=map_id,
        zone_name=(data["zone_name"] or "").strip(),
        x_ratio=x_ratio,
        y_ratio=y_ratio,
    )
    if not callout.zone_name:
        return jsonify({"error": "zone_name cannot be empty"}), 400

    db.session.add(callout)
    db.session.commit()
    return jsonify({"callout": callout.to_dict()}), 201


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["PUT"])
def update_callout(map_id, callout_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result

    callout, err = get_callout_of_map_or_404(map_id, callout_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    if "zone_name" in data:
        callout.zone_name = (data["zone_name"] or "").strip()
        if not callout.zone_name:
            return jsonify({"error": "zone_name cannot be empty"}), 400
    for key in ("x_ratio", "y_ratio"):
        if key in data:
            try:
                value = float(data[key])
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} must be numeric"}), 400
            if not 0 <= value <= 1:
                return (
                    jsonify({"error": f"{key} must be between 0 and 1"}),
                    400,
                )
            setattr(callout, key, value)

    db.session.commit()
    return jsonify({"callout": callout.to_dict()}), 200


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["DELETE"])
def delete_callout(map_id, callout_id):
    result = get_map_or_404(map_id)
    if isinstance(result, tuple):
        return result

    callout, err = get_callout_of_map_or_404(map_id, callout_id)
    if err:
        return err

    db.session.delete(callout)
    db.session.commit()
    return jsonify({"message": "Callout deleted successfully"}), 200
