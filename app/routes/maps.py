from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import admin_required
from app.serializers import serialize_callout_public, serialize_map_public
from app.services import map_service

maps_bp = Blueprint("maps", __name__, url_prefix="/api/maps")


@maps_bp.route("", methods=["GET"])
def list_maps():
    items, meta = paginate(map_service.list_maps())
    return jsonify({"maps": [serialize_map_public(m) for m in items], "meta": meta}), 200


@maps_bp.route("", methods=["POST"])
@admin_required()
def create_map(_admin):
    data = request.get_json(silent=True) or {}
    new_map = map_service.create_map(data)
    return jsonify({"map": serialize_map_public(new_map)}), 201


@maps_bp.route("/<int:map_id>", methods=["GET"])
def get_map(map_id):
    return jsonify({"map": serialize_map_public(map_service.get_map(map_id))}), 200


@maps_bp.route("/<int:map_id>", methods=["PUT"])
@admin_required()
def update_map(_admin, map_id):
    data = request.get_json(silent=True) or {}
    return jsonify({"map": serialize_map_public(map_service.update_map(map_id, data))}), 200


@maps_bp.route("/<int:map_id>", methods=["DELETE"])
@admin_required()
def delete_map(_admin, map_id):
    map_service.delete_map(map_id)
    return jsonify({"message": "Map deleted successfully"}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["GET"])
def list_callouts(map_id):
    callouts = map_service.list_callouts(map_id)
    return jsonify({"callouts": [serialize_callout_public(c) for c in callouts]}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["POST"])
@admin_required()
def create_callout(_admin, map_id):
    data = request.get_json(silent=True) or {}
    callout = map_service.create_callout(map_id, data)
    return jsonify({"callout": serialize_callout_public(callout)}), 201


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["GET"])
def get_callout(map_id, callout_id):
    callout = map_service.get_callout(map_id, callout_id)
    return jsonify({"callout": serialize_callout_public(callout)}), 200


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["PUT"])
@admin_required()
def update_callout(_admin, map_id, callout_id):
    data = request.get_json(silent=True) or {}
    callout = map_service.update_callout(map_id, callout_id, data)
    return jsonify({"callout": serialize_callout_public(callout)}), 200


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["DELETE"])
@admin_required()
def delete_callout(_admin, map_id, callout_id):
    map_service.delete_callout(map_id, callout_id)
    return jsonify({"message": "Callout deleted successfully"}), 200
