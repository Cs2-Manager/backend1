from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import jwt_required, jwt_optional
from app.serializers import serialize_lineup_public
from app.services import lineup_service

lineups_bp = Blueprint("lineups", __name__, url_prefix="/api/lineups")


def _filters():
    return {
        "map_id": request.args.get("map_id"),
        "type": request.args.get("type"),
        "side": request.args.get("side"),
        "q": request.args.get("q"),
        "difficulty": request.args.get("difficulty"),
    }


@lineups_bp.route("", methods=["GET"])
@jwt_optional()
def list_lineups(viewer):
    items, meta = paginate(lineup_service.list_lineups(_filters(), viewer))
    return jsonify({"lineups": [serialize_lineup_public(l) for l in items], "meta": meta}), 200


@lineups_bp.route("", methods=["POST"])
@jwt_required()
def create_lineup(_admin):
    data = request.get_json(silent=True) or {}
    lineup = lineup_service.create_lineup(data, _admin)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 201


@lineups_bp.route("/<int:lineup_id>", methods=["GET"])
@jwt_optional()
def get_lineup(viewer, lineup_id):
    lineup = lineup_service.get_lineup(lineup_id, viewer)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 200


@lineups_bp.route("/<int:lineup_id>", methods=["PUT"])
@jwt_required()
def update_lineup(_admin, lineup_id):
    data = request.get_json(silent=True) or {}
    lineup = lineup_service.update_lineup(lineup_id, data, _admin)
    return jsonify({"lineup": serialize_lineup_public(lineup)}), 200


@lineups_bp.route("/<int:lineup_id>", methods=["DELETE"])
@jwt_required()
def delete_lineup(_admin, lineup_id):
    lineup_service.delete_lineup(lineup_id, _admin)
    return jsonify({"message": "Lineup deleted successfully"}), 200


@lineups_bp.post('/<int:lineup_id>/duplicate')
@jwt_required()
def duplicate(user, lineup_id):
    return jsonify(lineup=serialize_lineup_public(lineup_service.duplicate(lineup_id, user))), 201


@lineups_bp.route('/<int:lineup_id>/favorite', methods=['PUT', 'DELETE'])
@jwt_required()
def favorite(user, lineup_id):
    lineup_service.favorite(lineup_id, user, request.method == 'PUT')
    return '', 204


@lineups_bp.get('/favorites')
@jwt_required()
def favorites(user):
    return jsonify(favorites=lineup_service.favorites(user))
