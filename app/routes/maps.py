from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import admin_required
from app.serializers import (
    serialize_callout_public,
    serialize_map_admin,
    serialize_map_public,
)
from app.services import map_service

maps_bp = Blueprint("maps", __name__, url_prefix="/api/maps")


def _filters():
    return {
        "q": request.args.get("q"),
        "pool": request.args.get("pool", "all"),
        "category": request.args.get("category"),
        "status": request.args.get("status"),
        "include_archived": request.args.get("include_archived") in ("1", "true"),
        "sort": request.args.get("sort", "name"),
    }


@maps_bp.route("", methods=["GET"])
def list_maps():
    items, meta = paginate(map_service.list_maps(_filters()))
    map_service.attach_official_counts(items)
    return jsonify({"maps": [serialize_map_public(m) for m in items], "meta": meta}), 200


@maps_bp.route("", methods=["POST"])
@admin_required()
def create_map(_admin):
    data = request.get_json(silent=True) or {}
    new_map = map_service.create_map(data)
    return jsonify({"map": serialize_map_admin(new_map)}), 201


@maps_bp.route("/<int:map_id>", methods=["GET"])
def get_map(map_id):
    return jsonify({"map": serialize_map_public(map_service.get_map(map_id))}), 200


@maps_bp.route("/<int:map_id>", methods=["PUT"])
@admin_required()
def update_map(_admin, map_id):
    data = request.get_json(silent=True) or {}
    return jsonify({"map": serialize_map_admin(map_service.update_map(map_id, data))}), 200


@maps_bp.route("/<int:map_id>", methods=["DELETE"])
@admin_required()
def delete_map(_admin, map_id):
    result = map_service.delete_map(map_id)
    message = (
        "Map archived because it is referenced by tactical content"
        if result["archived"]
        else "Map deleted successfully"
    )
    return jsonify({"message": message, "archived": result["archived"]}), 200


@maps_bp.route("/<int:map_id>/archive", methods=["POST"])
@admin_required()
def archive_map(_admin, map_id):
    return jsonify({"map": serialize_map_admin(map_service.archive_map(map_id))}), 200


@maps_bp.route("/<int:map_id>/unarchive", methods=["POST"])
@admin_required()
def unarchive_map(_admin, map_id):
    return jsonify({"map": serialize_map_admin(map_service.unarchive_map(map_id))}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["GET"])
def list_callouts(map_id):
    callouts = map_service.list_callouts(map_id)
    return jsonify({"callouts": [serialize_callout_public(c) for c in callouts]}), 200


@maps_bp.route("/<int:map_id>/callouts", methods=["POST"])
@admin_required()
def create_callout(_admin, map_id):
    data = request.get_json(silent=True) or {}
    callout = map_service.create_callout(map_id, data, _admin)
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
