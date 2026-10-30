from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import admin_required
from app.serializers import serialize_lineup_public
from app.services import lineup_service

lineups_bp = Blueprint("lineups", __name__, url_prefix="/api/lineups")


def _filters():
    return {
        "map_id": request.args.get("map_id"),
        "type": request.args.get("type"),
        "side": request.args.get("side"),
    }


@lineups_bp.route("", methods=["GET"])
def list_lineups():
    items, meta = paginate(lineup_service.list_lineups(_filters()))
    return jsonify({"lineups": [serialize_lineup_public(l) for l in items], "meta": meta}), 200


@lineups_bp.route("", methods=["POST"])
@admin_required()
def create_lineup(_admin):
    data = request.get_json(silent=True) or {}
    lineup = lineup_service.create_lineup(data)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 201


@lineups_bp.route("/<int:lineup_id>", methods=["GET"])
def get_lineup(lineup_id):
    lineup = lineup_service.get_lineup(lineup_id)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 200


@lineups_bp.route("/<int:lineup_id>", methods=["PUT"])
@admin_required()
def update_lineup(_admin, lineup_id):
    data = request.get_json(silent=True) or {}
    lineup = lineup_service.update_lineup(lineup_id, data)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 200


@lineups_bp.route("/<int:lineup_id>", methods=["DELETE"])
@admin_required()
def delete_lineup(_admin, lineup_id):
    lineup_service.delete_lineup(lineup_id)
    return jsonify({"message": "Lineup deleted successfully"}), 200
