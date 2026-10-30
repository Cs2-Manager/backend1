from flask import Blueprint, jsonify, request
from app.security import jwt_required

teams_bp = Blueprint("teams", __name__, url_prefix="/api/teams")


@teams_bp.route("", methods=["GET"])
@jwt_required()
def list_teams(user):
    return jsonify({"teams": [{"id": 1, "name": "Test Team"}]}), 200


@teams_bp.route("/mine", methods=["GET"])
@jwt_required()
def get_my_team(user):
    return jsonify({"team": {"id": 1, "name": "My Team"}}), 200


@teams_bp.route("/invitations", methods=["GET"])
@jwt_required()
def list_invitations(user):
    return jsonify({"invitations": []}), 200


@teams_bp.route("/<int:team_id>", methods=["GET", "PUT"])
@jwt_required()
def get_or_update_team(user, team_id):
    """Obtiene o actualiza un equipo por ID.

    GET: Ver equipo público/privado según visibilidad.
    PUT: Actualizar datos del equipo.
    """
    from app.services import team_service

    team = team_service.get_team_for_viewer(user, team_id)
    if team is None:
        return jsonify({"error": "Team not found"}), 404
    return jsonify({"team": team_service.team_payload(team, user)}), 200


@teams_bp.route("/<int:team_id>", methods=["DELETE"])
@jwt_required()
def delete_team(user, team_id):
    from app.services import team_service

    team_service.delete_team(user, team_id)
    return "", 204


@teams_bp.route("/<int:team_id>/members", methods=["GET"])
@jwt_required()
def list_team_members(user, team_id):
    from app.services import team_service

    team, role = team_service.get_team_for_viewer(user, team_id)
    team_service.ensure_team_visible(user, team, role=role)
    members = team_service.team_members_payload(team)
    return jsonify({"members": members, "meta": {"total": len(members)}}), 200


@teams_bp.route("/<int:team_id>/invitations", methods=["POST"])
@jwt_required()
def invite_member(user, team_id):
    from app.services import team_service

    invitation = team_service.invite_member(
        user, team_id, request.get_json(silent=True) or {}
    )
    return jsonify({"invitation": invitation.serialize()}), 201


@teams_bp.route("/<int:team_id>/invitations", methods=["GET"])
@jwt_required()
def list_team_invitations(user, team_id):
    from app.services import team_service

    query = team_service.list_team_invitations(
        user, team_id, request.args.get("status")
    )
    items, meta = team_service.paginate(query)
    return jsonify(
        {
            "invitations": [inv.serialize() for inv in items],
            "meta": meta,
        }
    ), 200
