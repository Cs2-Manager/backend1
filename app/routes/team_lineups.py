"""Rutas REST de las alineaciones competitivas de un equipo.

- `GET  /api/teams/<id>/lineups`
- `POST /api/teams/<id>/lineups`
- `GET  /api/teams/<id>/lineups/<lid>`
- `PUT  /api/teams/<id>/lineups/<lid>`
- `DELETE /api/teams/<id>/lineups/<lid>`
- `PUT  /api/teams/<id>/lineups/<lid>/players`
- `POST /api/teams/<id>/lineups/<lid>/activate`
- `POST /api/teams/<id>/lineups/<lid>/deactivate`
- `POST /api/teams/<id>/lineups/<lid>/primary`

Las lecturas respetan la visibilidad del equipo. Las escrituras se autorizan
por rol en la capa de permisos; el frontend nunca decide la autorización.
"""

from flask import Blueprint, jsonify, request

from app.security import jwt_optional, jwt_required
from app.services import team_lineup_service

team_lineups_bp = Blueprint(
    "team_lineups", __name__, url_prefix="/api/teams"
)


def _payload(lineup, viewer, role):
    return team_lineup_service.lineup_payload(lineup, viewer, role)


def _lineup_response(lineup, viewer, role, status_code=200):
    return (
        jsonify(
            {
                "lineup": _payload(lineup, viewer, role),
                "limits": team_lineup_service.LIMITS,
            }
        ),
        status_code,
    )


@team_lineups_bp.route("/<int:team_id>/lineups", methods=["GET"])
@jwt_optional()
def list_lineups(viewer, team_id):
    team, lineups, role = team_lineup_service.list_lineups(viewer, team_id)
    return (
        jsonify(
            {
                "lineups": [
                    _payload(lineup, viewer, role) for lineup in lineups
                ],
                "limits": team_lineup_service.LIMITS,
                "meta": {"total": len(lineups)},
            }
        ),
        200,
    )


@team_lineups_bp.route("/<int:team_id>/lineups", methods=["POST"])
@jwt_required()
def create_lineup(user, team_id):
    lineup = team_lineup_service.create_lineup(
        user, team_id, request.get_json(silent=True) or {}
    )
    team, _, role = team_lineup_service.get_lineup(
        user, team_id, lineup.id
    )
    return _lineup_response(lineup, user, role, 201)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>", methods=["GET"]
)
@jwt_optional()
def get_lineup(viewer, team_id, lineup_id):
    _, lineup, role = team_lineup_service.get_lineup(
        viewer, team_id, lineup_id
    )
    return _lineup_response(lineup, viewer, role)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>", methods=["PUT"]
)
@jwt_required()
def update_lineup(user, team_id, lineup_id):
    lineup = team_lineup_service.update_lineup(
        user, team_id, lineup_id, request.get_json(silent=True) or {}
    )
    team, lineup, role = team_lineup_service.get_lineup(
        user, team_id, lineup_id
    )
    return _lineup_response(lineup, user, role)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>", methods=["DELETE"]
)
@jwt_required()
def delete_lineup(user, team_id, lineup_id):
    team_lineup_service.delete_lineup(user, team_id, lineup_id)
    return "", 204


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>/players", methods=["PUT"]
)
@jwt_required()
def replace_lineup_players(user, team_id, lineup_id):
    team_lineup_service.replace_players(
        user, team_id, lineup_id, request.get_json(silent=True) or {}
    )
    team, lineup, role = team_lineup_service.get_lineup(
        user, team_id, lineup_id
    )
    return _lineup_response(lineup, user, role)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>/activate", methods=["POST"]
)
@jwt_required()
def activate_lineup(user, team_id, lineup_id):
    team_lineup_service.activate_lineup(user, team_id, lineup_id)
    team, lineup, role = team_lineup_service.get_lineup(
        user, team_id, lineup_id
    )
    return _lineup_response(lineup, user, role)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>/deactivate", methods=["POST"]
)
@jwt_required()
def deactivate_lineup(user, team_id, lineup_id):
    team_lineup_service.deactivate_lineup(user, team_id, lineup_id)
    team, lineup, role = team_lineup_service.get_lineup(
        user, team_id, lineup_id
    )
    return _lineup_response(lineup, user, role)


@team_lineups_bp.route(
    "/<int:team_id>/lineups/<int:lineup_id>/primary", methods=["POST"]
)
@jwt_required()
def set_primary_lineup(user, team_id, lineup_id):
    team_lineup_service.set_primary_lineup(user, team_id, lineup_id)
    team, lineup, role = team_lineup_service.get_lineup(
        user, team_id, lineup_id
    )
    return _lineup_response(lineup, user, role)
