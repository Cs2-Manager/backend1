"""Rutas REST de la biblioteca de lineups de granadas.

Convive con los endpoints históricos `/api/lineups` (que se conservan para
compatibilidad) y agrega el modelo de scopes:

- OFFICIAL: catálogo público; solo administradores escriben.
- PERSONAL: contenido privado del autor.
- TEAM: contenido compartido y editable por integrantes actuales del equipo.

La privacidad se resuelve en el servicio: los recursos privados ajenos
responden 404 para no revelar su existencia.
"""

from flask import Blueprint, jsonify, request

from app.errors import ApiError
from app.extensions import db
from app.models.team import TeamMember
from app.pagination import paginate
from app.security import admin_required, jwt_optional, jwt_required
from app.serializers import serialize_grenade_proposal
from app.services import grenade_lineup_service

grenade_lineups_bp = Blueprint("grenade_lineups", __name__)


def _filters():
    return {
        "q": request.args.get("q"),
        "type": request.args.get("type"),
        "side": request.args.get("side"),
        "difficulty": request.args.get("difficulty"),
        "map_id": request.args.get("map_id"),
        "team_id": request.args.get("team_id"),
        "status": request.args.get("status"),
        "include_archived": request.args.get("include_archived"),
    }


def _serialized(items, viewer):
    return [
        grenade_lineup_service.serialize_for_viewer(item, viewer)
        for item in items
    ]


# --- Listados ---------------------------------------------------------------


@grenade_lineups_bp.get("/api/maps/<int:map_id>/lineups")
@jwt_optional()
def list_map_lineups(viewer, map_id):
    scope = (request.args.get("scope") or "OFFICIAL").upper()
    query, _map_obj = grenade_lineup_service.list_map_lineups(
        map_id, viewer, scope=scope, filters=_filters()
    )
    items, meta = paginate(query)
    return (
        jsonify({"lineups": _serialized(items, viewer), "meta": meta}),
        200,
    )


@grenade_lineups_bp.get("/api/grenade-lineups/personal")
@jwt_required()
def list_personal_lineups(user):
    query = grenade_lineup_service.personal_query(user, _filters())
    items, meta = paginate(query)
    return (
        jsonify({"lineups": _serialized(items, user), "meta": meta}),
        200,
    )


@grenade_lineups_bp.get("/api/grenade-lineups/team")
@jwt_required()
def list_team_lineups(user):
    team_id = request.args.get("team_id")
    if team_id in (None, ""):
        membership = (
            db.session.query(TeamMember).filter_by(user_id=user.id).first()
        )
        if membership is None:
            raise ApiError("You are not a member of a team", status_code=403)
        team_id = membership.team_id
    else:
        try:
            team_id = int(team_id)
        except (TypeError, ValueError) as error:
            raise ApiError("Invalid team_id", status_code=400) from error
    query = grenade_lineup_service.team_query(team_id, user, _filters())
    items, meta = paginate(query)
    return (
        jsonify({"lineups": _serialized(items, user), "meta": meta}),
        200,
    )


@grenade_lineups_bp.get("/api/teams/<int:team_id>/grenade-lineups")
@jwt_required()
def list_team_lineups_by_team(user, team_id):
    query = grenade_lineup_service.team_query(team_id, user, _filters())
    items, meta = paginate(query)
    return (
        jsonify({"lineups": _serialized(items, user), "meta": meta}),
        200,
    )


# --- CRUD -------------------------------------------------------------------


@grenade_lineups_bp.post("/api/maps/<int:map_id>/lineups")
@jwt_required()
def create_lineup(user, map_id):
    data = request.get_json(silent=True) or {}
    scope = (request.args.get("scope") or data.get("scope") or "PERSONAL").upper()
    lineup = grenade_lineup_service.create_lineup(map_id, data, user, scope=scope)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, user)}),
        201,
    )


@grenade_lineups_bp.get("/api/grenade-lineups/<int:lineup_id>")
@jwt_optional()
def get_lineup(viewer, lineup_id):
    lineup = grenade_lineup_service.get_lineup(lineup_id, viewer)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, viewer)}),
        200,
    )


@grenade_lineups_bp.put("/api/grenade-lineups/<int:lineup_id>")
@jwt_required()
def update_lineup(user, lineup_id):
    data = request.get_json(silent=True) or {}
    lineup = grenade_lineup_service.update_lineup(lineup_id, data, user)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, user)}),
        200,
    )


@grenade_lineups_bp.delete("/api/grenade-lineups/<int:lineup_id>")
@jwt_required()
def delete_lineup(user, lineup_id):
    grenade_lineup_service.delete_lineup(lineup_id, user)
    return jsonify({"message": "Lineup deleted successfully"}), 200


@grenade_lineups_bp.post("/api/grenade-lineups/<int:lineup_id>/publish")
@admin_required()
def publish_official(user, lineup_id):
    lineup = grenade_lineup_service.publish_official(lineup_id, user)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, user)}),
        200,
    )


@grenade_lineups_bp.post("/api/grenade-lineups/<int:lineup_id>/archive")
@admin_required()
def archive_official(user, lineup_id):
    lineup = grenade_lineup_service.archive_official(lineup_id, user)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, user)}),
        200,
    )


# --- Historial y restauración ----------------------------------------------


@grenade_lineups_bp.get("/api/grenade-lineups/<int:lineup_id>/revisions")
@jwt_required()
def list_revisions(user, lineup_id):
    lineup, revisions = grenade_lineup_service.list_revisions(lineup_id, user)
    return (
        jsonify(
            {
                "lineup_id": lineup.id,
                "version": lineup.version,
                "revisions": revisions,
            }
        ),
        200,
    )


@grenade_lineups_bp.post(
    "/api/grenade-lineups/<int:lineup_id>/revisions/<int:version>/restore"
)
@jwt_required()
def restore_revision(user, lineup_id, version):
    data = request.get_json(silent=True) or {}
    lineup = grenade_lineup_service.restore_revision(lineup_id, version, data, user)
    return (
        jsonify({"lineup": grenade_lineup_service.serialize_for_viewer(lineup, user)}),
        200,
    )


# --- Propuestas -------------------------------------------------------------


@grenade_lineups_bp.post("/api/grenade-lineups/<int:lineup_id>/propose")
@jwt_required()
def propose(user, lineup_id):
    data = request.get_json(silent=True) or {}
    proposal = grenade_lineup_service.propose(lineup_id, data, user)
    return jsonify({"proposal": serialize_grenade_proposal(proposal)}), 201


@grenade_lineups_bp.get("/api/grenade-lineups/proposals")
@jwt_required()
def list_my_proposals(user):
    query = grenade_lineup_service.list_my_proposals(
        user, request.args.get("status")
    )
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "proposals": [serialize_grenade_proposal(item) for item in items],
                "meta": meta,
            }
        ),
        200,
    )


@grenade_lineups_bp.get("/api/grenade-lineups/proposals/<int:proposal_id>")
@jwt_required()
def get_proposal(user, proposal_id):
    proposal = grenade_lineup_service.get_proposal(proposal_id, user)
    return jsonify({"proposal": serialize_grenade_proposal(proposal)}), 200


@grenade_lineups_bp.post(
    "/api/grenade-lineups/proposals/<int:proposal_id>/approve"
)
@jwt_required()
def approve_proposal(user, proposal_id):
    data = request.get_json(silent=True) or {}
    proposal, lineup = grenade_lineup_service.approve_proposal(
        proposal_id, user, data
    )
    return (
        jsonify(
            {
                "proposal": serialize_grenade_proposal(proposal),
                "lineup": grenade_lineup_service.serialize_for_viewer(lineup, user),
            }
        ),
        200,
    )


@grenade_lineups_bp.post(
    "/api/grenade-lineups/proposals/<int:proposal_id>/reject"
)
@jwt_required()
def reject_proposal(user, proposal_id):
    data = request.get_json(silent=True) or {}
    proposal = grenade_lineup_service.reject_proposal(proposal_id, user, data)
    return jsonify({"proposal": serialize_grenade_proposal(proposal)}), 200


@grenade_lineups_bp.post(
    "/api/grenade-lineups/proposals/<int:proposal_id>/cancel"
)
@jwt_required()
def cancel_proposal(user, proposal_id):
    proposal = grenade_lineup_service.cancel_proposal(proposal_id, user)
    return jsonify({"proposal": serialize_grenade_proposal(proposal)}), 200


@grenade_lineups_bp.get("/api/teams/<int:team_id>/grenade-proposals")
@jwt_required()
def list_team_proposals(user, team_id):
    query = grenade_lineup_service.list_team_proposals(
        team_id, user, request.args.get("status")
    )
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "proposals": [serialize_grenade_proposal(item) for item in items],
                "meta": meta,
            }
        ),
        200,
    )
