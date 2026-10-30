from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import admin_required
from app.serializers import serialize_workshop_map_public
from app.services import workshop_service

workshop_maps_bp = Blueprint(
    "workshop_maps", __name__, url_prefix="/api/workshop-maps"
)


@workshop_maps_bp.route("", methods=["GET"])
def list_workshop_maps():
    category = request.args.get("category")
    items, meta = paginate(workshop_service.list_workshop_maps(category))
    return (
        jsonify(
            {
                "workshop_maps": [serialize_workshop_map_public(w) for w in items],
                "meta": meta,
            }
        ),
        200,
    )


@workshop_maps_bp.route("", methods=["POST"])
@admin_required()
def create_workshop_map(_admin):
    data = request.get_json(silent=True) or {}
    workshop_map = workshop_service.create_workshop_map(data)
    return jsonify({"workshop_map": serialize_workshop_map_public(workshop_map)}), 201


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["GET"])
def get_workshop_map(workshop_map_id):
    item = workshop_service.get_workshop_map(workshop_map_id)
    return jsonify({"workshop_map": serialize_workshop_map_public(item)}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["PUT"])
@admin_required()
def update_workshop_map(_admin, workshop_map_id):
    data = request.get_json(silent=True) or {}
    item = workshop_service.update_workshop_map(workshop_map_id, data)
    return jsonify({"workshop_map": serialize_workshop_map_public(item)}), 200


@workshop_maps_bp.route("/<int:workshop_map_id>", methods=["DELETE"])
@admin_required()
def delete_workshop_map(_admin, workshop_map_id):
    workshop_service.delete_workshop_map(workshop_map_id)
    return jsonify({"message": "Workshop map deleted successfully"}), 200
