"""Rutas de autenticación, vinculación y sincronización con Steam."""

from flask import Blueprint, jsonify, redirect, request

from app.errors import ApiError
from app.security import jwt_required
from app.services import steam_service
from app.validators import clean_str

steam_bp = Blueprint("steam", __name__, url_prefix="/api")


@steam_bp.route("/auth/steam/start", methods=["GET"])
def steam_start():
    try:
        url = steam_service.start_intent("LOGIN")
    except ApiError as error:
        code = "not_configured" if error.status_code == 503 else "invalid_state"
        return redirect(
            steam_service.frontend_callback_url(error=code), code=302
        )
    return redirect(url, code=302)


@steam_bp.route("/auth/steam/callback", methods=["GET"])
def steam_callback():
    return redirect(
        steam_service.process_callback(request.args), code=302
    )


@steam_bp.route("/auth/steam/exchange", methods=["POST"])
def steam_exchange():
    data = request.get_json(silent=True) or {}
    handoff = clean_str(data.get("handoff"))
    if not handoff:
        raise ApiError("Missing Steam handoff code", status_code=400)
    return jsonify(steam_service.exchange_handoff(handoff)), 200


@steam_bp.route("/steam/status", methods=["GET"])
@jwt_required()
def steam_status(user):
    return jsonify({"steam": steam_service.build_steam_section(user, owner=True)})


@steam_bp.route("/steam/link", methods=["POST"])
@jwt_required()
def steam_link(user):
    url = steam_service.start_intent("LINK", user=user)
    return jsonify({"authorization_url": url}), 200


@steam_bp.route("/steam/account", methods=["DELETE"])
@jwt_required()
def steam_unlink(user):
    steam_service.unlink_account(user)
    return (
        jsonify(
            {
                "message": "Steam account unlinked",
                "steam": steam_service.build_steam_section(user, owner=True),
            }
        ),
        200,
    )


@steam_bp.route("/steam/sync", methods=["POST"])
@jwt_required()
def steam_sync(user):
    result = steam_service.sync_account(user)
    return jsonify(result), 200
