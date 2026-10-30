"""Rutas REST de equipos, integrantes e invitaciones.

- `/api/teams`: directorio público y creación de equipos.
- `/api/teams/mine`: equipo activo del usuario autenticado.
- `/api/teams/<id>`: perfil público/privado según visibilidad.
- `/api/teams/<id>/members`: integrantes con la misma política de privacidad.
- `/api/teams/<id>/invitations`: gestión de invitaciones del equipo.
- `/api/teams/invitations`: invitaciones recibidas por el usuario.
"""

from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import jwt_optional, jwt_required
from app.serializers import (
    serialize_invitation,
    serialize_team_member,
    serialize_team_summary,
)
from app.services import team_service

teams_bp = Blueprint("teams", __name__, url_prefix="/api/teams")


@teams_bp.route("", methods=["GET"])
def list_teams():
    query = team_service.list_public_teams(request.args.get("search"))
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "teams": [serialize_team_summary(team) for team in items],
                "meta": meta,
            }
        ),
        200,
    )


@teams_bp.route("", methods=["POST"])
@jwt_required()
def create_team(user):
    team = team_service.create_team(
        user, request.get_json(silent=True) or {}
    )
    return jsonify({"team": team_service.team_payload(team, user)}), 201


@teams_bp.route("/mine", methods=["GET"])
@jwt_required()
def get_my_team(user):
    return jsonify({"team": team_service.get_my_team(user)}), 200


@teams_bp.route("/invitations", methods=["GET"])
@jwt_required()
def list_my_invitations(user):
    query = team_service.list_my_invitations(
        user, request.args.get("status")
    )
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "invitations": [
                    serialize_invitation(invitation) for invitation in items
                ],
                "meta": meta,
            }
        ),
        200,
    )


@teams_bp.route(
    "/invitations/<int:invitation_id>/accept", methods=["POST"]
)
@jwt_required()
def accept_invitation(user, invitation_id):
    invitation = team_service.accept_invitation(user, invitation_id)
    team = team_service.get_team_for_viewer(user, invitation.team_id)[0]
    return (
        jsonify(
            {
                "invitation": serialize_invitation(invitation),
                "team": team_service.team_payload(team, user),
            }
        ),
        200,
    )


@teams_bp.route(
    "/invitations/<int:invitation_id>/reject", methods=["POST"]
)
@jwt_required()
def reject_invitation(user, invitation_id):
    invitation = team_service.reject_invitation(user, invitation_id)
    return jsonify({"invitation": serialize_invitation(invitation)}), 200


@teams_bp.route("/<int:team_id>", methods=["GET"])
@jwt_optional()
def get_team(viewer, team_id):
    team, role = team_service.get_team_for_viewer(viewer, team_id)
    return (
        jsonify({"team": team_service.team_payload(team, viewer, role=role)}),
        200,
    )


@teams_bp.route("/<int:team_id>", methods=["PUT"])
@jwt_required()
def update_team(user, team_id):
    team = team_service.update_team(
        user, team_id, request.get_json(silent=True) or {}
    )
    return jsonify({"team": team_service.team_payload(team, user)}), 200


@teams_bp.route("/<int:team_id>/members", methods=["GET"])
@jwt_optional()
def list_team_members(viewer, team_id):
    team, role = team_service.get_team_for_viewer(viewer, team_id)
    team_service.ensure_team_visible(viewer, team, role=role)
    members = team_service.team_members_payload(team)
    return jsonify({"members": members, "meta": {"total": len(members)}}), 200


@teams_bp.route("/<int:team_id>/invitations", methods=["POST"])
@jwt_required()
def invite_member(user, team_id):
    invitation = team_service.invite_member(
        user, team_id, request.get_json(silent=True) or {}
    )
    return jsonify({"invitation": serialize_invitation(invitation)}), 201


@teams_bp.route("/<int:team_id>/invitations", methods=["GET"])
@jwt_required()
def list_team_invitations(user, team_id):
    query = team_service.list_team_invitations(
        user, team_id, request.args.get("status")
    )
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "invitations": [
                    serialize_invitation(invitation) for invitation in items
                ],
                "meta": meta,
            }
        ),
        200,
    )


@teams_bp.route(
    "/<int:team_id>/invitations/<int:invitation_id>", methods=["DELETE"]
)
@jwt_required()
def cancel_invitation(user, team_id, invitation_id):
    team_service.cancel_invitation(user, team_id, invitation_id)
    return "", 204


@teams_bp.route(
    "/<int:team_id>/members/<int:member_user_id>", methods=["DELETE"]
)
@jwt_required()
def remove_member(user, team_id, member_user_id):
    team_service.remove_member(user, team_id, member_user_id)
    return "", 204


@teams_bp.route(
    "/<int:team_id>/members/<int:member_user_id>", methods=["PATCH"]
)
@jwt_required()
def update_member_role(user, team_id, member_user_id):
    membership = team_service.update_member_role(
        user,
        team_id,
        member_user_id,
        request.get_json(silent=True) or {},
    )
    return jsonify({"member": serialize_team_member(membership)}), 200


@teams_bp.route("/<int:team_id>/leave", methods=["POST"])
@jwt_required()
def leave_team(user, team_id):
    team_service.leave_team(user, team_id)
    return "", 204


@teams_bp.route("/<int:team_id>/transfer-captain", methods=["POST"])
@jwt_required()
def transfer_captain(user, team_id):
    team = team_service.transfer_captain(
        user, team_id, request.get_json(silent=True) or {}
    )
    return jsonify({"team": team_service.team_payload(team, user)}), 200
