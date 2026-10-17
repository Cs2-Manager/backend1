from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import jwt_required
from app.services import workshop_service

workshop_maps_bp = Blueprint(
    "workshop_maps", __name__, url_prefix="/api/workshop-maps"
)


@workshop_maps_bp.route("", methods=["GET"])
def list_workshop_maps():
    category = request.args.get("category")
    items, meta = paginate(workshop_service.list_workshop_maps(category))
    return (
        jsonify({"workshop_maps": [w.to_dict() for w in items], "meta": meta}),
        200,
    )


@workshop_maps_bp.route("", methods=["POST"])
@jwt_required()
def create_workshop_map(_user):
    data = request.get_json(silent=True) or {}
    workshop_map = workshop_service.create_workshop_map(data)
    return jsonify({"workshop_map": workshop_map.to_dict()}), 201


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["GET"])
def get_workshop_map(workshop_map_id):
    item = workshop_service.get_workshop_map(workshop_map_id)
    return jsonify({"workshop_map": item.to_dict()}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["PUT"])
@jwt_required()
def update_workshop_map(_user, workshop_map_id):
    data = request.get_json(silent=True) or {}
    item = workshop_service.update_workshop_map(workshop_map_id, data)
    return jsonify({"workshop_map": item.to_dict()}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["DELETE"])
@jwt_required()
def delete_workshop_map(_user, workshop_map_id):
    workshop_service.delete_workshop_map(workshop_map_id)
    return jsonify({"message": "Workshop map deleted successfully"}), 200
