from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import jwt_required
from app.services import map_service

maps_bp = Blueprint("maps", __name__, url_prefix="/api/maps")


@maps_bp.route("", methods=["GET"])
def list_maps():
    items, meta = paginate(map_service.list_maps())
    return jsonify({"maps": [m.to_dict() for m in items], "meta": meta}), 200


@maps_bp.route("", methods=["POST"])
@jwt_required()
def create_map(_user):
    data = request.get_json(silent=True) or {}
    new_map = map_service.create_map(data)
    return jsonify({"map": new_map.to_dict()}), 201


@maps_bp.route("/<int:map_id>", methods=["GET"])
def get_map(map_id):
    return jsonify({"map": map_service.get_map(map_id).to_dict()}), 200


@maps_bp.route("/<int:map_id>", methods=["PUT"])
@jwt_required()
def update_map(_user, map_id):
    data = request.get_json(silent=True) or {}
    return jsonify({"map": map_service.update_map(map_id, data).to_dict()}), 200


@maps_bp.route("/<int:map_id>", methods=["DELETE"])
@jwt_required()
def delete_map(_user, map_id):
    map_service.delete_map(map_id)
    return jsonify({"message": "Map deleted successfully"}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["GET"])
def list_callouts(map_id):
    callouts = map_service.list_callouts(map_id)
    return jsonify({"callouts": [c.to_dict() for c in callouts]}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["POST"])
@jwt_required()
def create_callout(_user, map_id):
    data = request.get_json(silent=True) or {}
    callout = map_service.create_callout(map_id, data)
    return jsonify({"callout": callout.to_dict()}), 201


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["GET"])
def get_callout(map_id, callout_id):
    callout = map_service.get_callout(map_id, callout_id)
    return jsonify({"callout": callout.to_dict()}), 200


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["PUT"])
@jwt_required()
def update_callout(_user, map_id, callout_id):
    data = request.get_json(silent=True) or {}
    callout = map_service.update_callout(map_id, callout_id, data)
    return jsonify({"callout": callout.to_dict()}), 200


@maps_bp.route("/<int:map_id>/callouts/<int:callout_id>", methods=["DELETE"])
@jwt_required()
def delete_callout(_user, map_id, callout_id):
    map_service.delete_callout(map_id, callout_id)
    return jsonify({"message": "Callout deleted successfully"}), 200
