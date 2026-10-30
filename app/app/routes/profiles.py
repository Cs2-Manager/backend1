from flask import Blueprint, jsonify, request
from app.security import jwt_required

profiles_bp = Blueprint("profiles", __name__, url_prefix="/api")


@profiles_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_own_profile(user):
    return jsonify({"profile": {"id": 1, "nickname": "test_user", "level": 1}}), 200


@profiles_bp.route("/players", methods=["GET"])
def list_players():
    return jsonify({"players": [{"id": 1, "nickname": "player1", "level": 5}]}), 200
