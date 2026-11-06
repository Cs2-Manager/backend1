"""Rutas de la sección CS2 MATCHMAKING.

Todas exigen JWT: la autorización, los share codes y las demos son datos del
jugador. La sección pública se entrega dentro del perfil y nunca expone
códigos, rutas ni errores internos.
"""

from flask import Blueprint, current_app, jsonify, request

from app.errors import ApiError
from app.security import jwt_required
from app.services import matchmaking_service

matchmaking_bp = Blueprint("matchmaking", __name__, url_prefix="/api")


def _max_upload_bytes():
    try:
        megabytes = int(
            current_app.config.get("MATCHMAKING_MAX_UPLOAD_MB", 512)
        )
    except (TypeError, ValueError):
        megabytes = 512
    return max(1, megabytes) * 1024 * 1024


@matchmaking_bp.route("/matchmaking/status", methods=["GET"])
@jwt_required()
def matchmaking_status(user):
    return jsonify(
        {"matchmaking": matchmaking_service.build_section(user, owner=True)}
    ), 200


@matchmaking_bp.route("/matchmaking/authorization", methods=["POST"])
@jwt_required()
def matchmaking_authorize(user):
    data = request.get_json(silent=True) or {}
    section = matchmaking_service.authorize(user, data)
    return jsonify({"matchmaking": section}), 200


@matchmaking_bp.route("/matchmaking/authorization", methods=["DELETE"])
@jwt_required()
def matchmaking_revoke(user):
    section = matchmaking_service.revoke(user)
    return jsonify(
        {
            "message": "Autorización de matchmaking revocada",
            "matchmaking": section,
        }
    ), 200


@matchmaking_bp.route("/matchmaking/sync", methods=["POST"])
@jwt_required()
def matchmaking_sync(user):
    result = matchmaking_service.request_sync(user)
    status_code = 202 if result.get("status") == "QUEUED" else 200
    return jsonify(result), status_code


@matchmaking_bp.route("/matchmaking/matches", methods=["GET"])
@jwt_required()
def matchmaking_matches(user):
    try:
        limit = int(request.args.get("limit", 25))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError) as error:
        raise ApiError("Parámetros de paginación inválidos", status_code=400) from error
    matches = matchmaking_service.list_matches(
        user, limit=limit, offset=offset, owner=True
    )
    return jsonify({"matches": matches, "count": len(matches)}), 200


@matchmaking_bp.route("/matchmaking/matches", methods=["POST"])
@jwt_required()
def matchmaking_add_match(user):
    data = request.get_json(silent=True) or {}
    match, created = matchmaking_service.register_manual_share_code(
        user, data.get("share_code")
    )
    from app.serializers.matchmaking import serialize_matchmaking_match

    return (
        jsonify(
            {
                "created": created,
                "match": serialize_matchmaking_match(match, owner=True),
            }
        ),
        201 if created else 200,
    )


@matchmaking_bp.route("/matchmaking/matches/<int:match_id>", methods=["GET"])
@jwt_required()
def matchmaking_match_detail(user, match_id):
    return jsonify(
        {"match": matchmaking_service.get_match(user, match_id, owner=True)}
    ), 200


@matchmaking_bp.route("/matchmaking/demos", methods=["POST"])
@jwt_required()
def matchmaking_upload_demo(user):
    length = request.content_length or 0
    if length > _max_upload_bytes():
        raise ApiError(
            "La demo supera el tamaño máximo permitido.", status_code=413
        )
    file_storage = request.files.get("demo") or request.files.get("file")
    return jsonify(matchmaking_service.upload_demo(user, file_storage)), 202
