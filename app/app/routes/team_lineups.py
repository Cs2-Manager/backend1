from flask import Blueprint, jsonify, request
from app.security import jwt_required

team_lineups_bp = Blueprint(
    "team_lineups", __name__, url_prefix="/api/teams/<int:team_id>/lineups"
)


@team_lineups_bp.route("", methods=["GET"])
@jwt_required()
def list_team_lineups(user):
    return jsonify({"lineups": []}), 200


@team_lineups_bp.route("", methods=["POST"])
@jwt_required()
def create_team_lineup(user):
    return jsonify({"lineup": {"id": 1, "name": "Test Lineup"}}), 201
