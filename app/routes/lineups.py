from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.lineup import GRENADE_TYPES, SIDES, Lineup
from app.models.map import Map
from app.video import is_valid_video_url

lineups_bp = Blueprint("lineups", __name__, url_prefix="/api/lineups")

REQUIRED_FIELDS = ("map_id", "type", "side", "title", "video_url")


def get_lineup_or_404(lineup_id):
    return db.session.get(Lineup, lineup_id) or (
        (jsonify({"error": "Lineup not found"}), 404)
    )


def validate_payload(data, partial=False):
    """Validate a lineup payload. Returns (errors, payload)."""
    errors = {}
    payload = {}

    for field in ("type", "side"):
        if partial and field not in data:
            continue
        value = (data.get(field) or "").strip()
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
        value = (data.get(field) or "").strip()
        if field == "title" and not value:
            errors[field] = "title is required"
        else:
            payload[field] = value

    if partial and "video_url" not in data:
        return errors, payload
    video_url = (data.get("video_url") or "").strip()
    if not video_url:
        errors["video_url"] = "video_url is required"
    elif not is_valid_video_url(video_url):
        errors["video_url"] = "video_url must be a valid YouTube link"
    else:
        payload["video_url"] = video_url

    return errors, payload


@lineups_bp.route("", methods=["GET"])
def list_lineups():
    query = db.session.query(Lineup)

    map_id = request.args.get("map_id")
    if map_id:
        if map_id.isdigit():
            query = query.filter(Lineup.map_id == int(map_id))
        else:
            return (
                jsonify({"error": "map_id must be an integer"}),
                400,
            )

    line_type = request.args.get("type")
    if line_type:
        if line_type not in GRENADE_TYPES:
            return (
                jsonify({"error": f"type must be one of {', '.join(GRENADE_TYPES)}"}),
                400,
            )
        query = query.filter(Lineup.type == line_type)

    side = request.args.get("side")
    if side:
        if side not in SIDES:
            return jsonify({"error": f"side must be one of {', '.join(SIDES)}"}), 400
        query = query.filter(Lineup.side == side)

    lineups = query.order_by(Lineup.title).all()
    return jsonify({"lineups": [l.to_dict() for l in lineups]}), 200


@lineups_bp.route("", methods=["POST"])
def create_lineup():
    data = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return (
            jsonify({"error": "Missing required fields", "fields": missing}),
            400,
        )

    errors, payload = validate_payload(data)
    if errors:
        return jsonify({"error": "Invalid lineup", "fields": errors}), 400

    lineup = Lineup(**payload)
    db.session.add(lineup)
    db.session.commit()
    return jsonify({"lineup": lineup.to_dict()}), 201


@lineups_bp.route("/<int:lineup_id>", methods=["PUT"])
def update_lineup(lineup_id):
    result = get_lineup_or_404(lineup_id)
    if isinstance(result, tuple):
        return result
    current = result

    data = request.get_json(silent=True) or {}
    errors, payload = validate_payload(data, partial=True)
    if errors:
        return jsonify({"error": "Invalid lineup", "fields": errors}), 400

    for key, value in payload.items():
        setattr(current, key, value)

    db.session.commit()
    return jsonify({"lineup": current.to_dict()}), 200


@lineups_bp.route("/<int:lineup_id>", methods=["DELETE"])
def delete_lineup(lineup_id):
    result = get_lineup_or_404(lineup_id)
    if isinstance(result, tuple):
        return result
    db.session.delete(result)
    db.session.commit()
    return jsonify({"message": "Lineup deleted successfully"}), 200
