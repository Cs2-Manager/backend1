"""Rutas de la integración con FACEIT.

Todas las rutas de datos exigen JWT: el historial, el ELO y las estadísticas
son información del jugador. El callback OAuth2 es público porque lo invoca el
navegador desde FACEIT, pero solo acepta un `state` de un solo uso que ya fue
emitido para un usuario autenticado.
"""

import logging
import re

from flask import Blueprint, jsonify, redirect, request

from app.security import jwt_required
from app.services import faceit_service

faceit_bp = Blueprint("faceit", __name__, url_prefix="/api")


class _OAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if "/api/faceit/oauth/callback?" in message:
            record.msg = re.sub(
                r"(/api/faceit/oauth/callback)\?[^\s\"']+", r"\1", message
            )
            record.args = ()
        return True


# Werkzeug registra por defecto la query completa, incluido el authorization
# code. El diagnóstico del callback debe contener solo categorías y HTTP.
logging.getLogger("werkzeug").addFilter(_OAuthAccessLogFilter())


@faceit_bp.route("/faceit/status", methods=["GET"])
@jwt_required()
def faceit_status(user):
    return jsonify(faceit_service.status_payload(user)), 200


@faceit_bp.route("/faceit/discover", methods=["POST"])
@jwt_required()
def faceit_discover(user):
    return jsonify({"discovery": faceit_service.discover(user)}), 200


@faceit_bp.route("/faceit/link", methods=["POST"])
@jwt_required()
def faceit_link(user):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    section = faceit_service.link_discovered(user, player_id=player_id)
    return (
        jsonify(
            {
                "message": "Cuenta de FACEIT vinculada correctamente.",
                "faceit": section,
            }
        ),
        200,
    )


@faceit_bp.route("/faceit/account", methods=["DELETE"])
@jwt_required()
def faceit_unlink(user):
    section = faceit_service.unlink(user)
    return (
        jsonify(
            {
                "message": "Cuenta de FACEIT desvinculada.",
                "faceit": section,
            }
        ),
        200,
    )


@faceit_bp.route("/faceit/sync", methods=["POST"])
@jwt_required()
def faceit_sync(user):
    data = request.get_json(silent=True) or {}
    result = faceit_service.sync(user, force=bool(data.get("force")))
    return jsonify(result), 200


@faceit_bp.route("/faceit/oauth/start", methods=["POST"])
@jwt_required()
def faceit_oauth_start(user):
    return (
        jsonify(
            {
                "authorization_url": faceit_service.start_oauth(user),
                "expires_in_seconds": faceit_service.oauth_request_ttl(),
            }
        ),
        200,
    )


@faceit_bp.route("/faceit/oauth/callback", methods=["GET"])
def faceit_oauth_callback():
    response = redirect(
        faceit_service.process_oauth_callback(request.args), code=302
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@faceit_bp.route("/faceit/matches", methods=["GET"])
@jwt_required()
def faceit_matches(user):
    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return (
        jsonify(
            faceit_service.list_matches(
                user,
                limit=limit,
                offset=offset,
                map_name=(request.args.get("map") or "").strip() or None,
                result=(request.args.get("result") or "").strip() or None,
            )
        ),
        200,
    )


@faceit_bp.route("/faceit/matches/<int:match_id>", methods=["GET"])
@jwt_required()
def faceit_match(user, match_id):
    refresh = str(request.args.get("refresh", "")).lower() in (
        "1",
        "true",
        "yes",
    )
    return (
        jsonify(
            {"match": faceit_service.get_match(user, match_id, refresh=refresh)}
        ),
        200,
    )


@faceit_bp.route("/faceit/maps", methods=["GET"])
@jwt_required()
def faceit_maps(user):
    return jsonify(faceit_service.list_maps(user)), 200


@faceit_bp.route("/faceit/elo", methods=["GET"])
@jwt_required()
def faceit_elo(user):
    return jsonify(faceit_service.list_elo_history(user)), 200
