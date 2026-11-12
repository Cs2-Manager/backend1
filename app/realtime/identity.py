"""Endpoint interno de verificación de identidad.

NestJS lo consulta opcionalmente al aceptar un socket para confirmar que el
usuario del JWT sigue existiendo en Flask. La ruta no se publica por nginx y
exige la misma firma HMAC que la API interna de eventos.
"""

import json
import threading
import time

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models.team import TeamMember
from app.models.user import User

from .signature import verify

realtime_internal_bp = Blueprint(
    "realtime_internal", __name__, url_prefix="/internal/realtime"
)

_nonce_lock = threading.Lock()
_seen_nonces = {}


def _remember_nonce(nonce, ttl_seconds):
    now = time.time()
    with _nonce_lock:
        expired = [
            key for key, expires_at in _seen_nonces.items() if expires_at <= now
        ]
        for key in expired:
            _seen_nonces.pop(key, None)
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = now + ttl_seconds
        return True


def _unauthorized(message):
    return jsonify({"error": message}), 401


def _validate_headers(request) -> tuple[str, str, str] | tuple[None, None, None]:
    timestamp = request.headers.get("X-Realtime-Timestamp", "")
    nonce = request.headers.get("X-Realtime-Nonce", "")
    signature = request.headers.get("X-Realtime-Signature", "")
    if not timestamp or not nonce or not signature:
        return None, None, None
    return timestamp, nonce, signature


def _validate_timestamp(timestamp: str, max_age: int) -> bool:
    if not timestamp.isdigit() or len(timestamp) != 10:
        return False
    if abs(int(time.time()) - int(timestamp)) > max_age:
        return False
    return True


def _validate_nonce(nonce: str) -> bool:
    return 8 <= len(nonce) <= 128


def _validate_user_id(payload: dict) -> int | None:
    user_id = payload.get("user_id")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        return None
    return user_id


def _lookup_user(user_id: int) -> User | None:
    return db.session.get(User, user_id)


def _lookup_membership(user_id: int):
    return (
        db.session.query(TeamMember)
        .filter(TeamMember.user_id == user_id)
        .first()
    )


def _checked_auth_headers():
    """Validate credential shape before signature verification or JSON parsing."""
    timestamp, nonce, signature = _validate_headers(request)
    if timestamp is None:
        return None, "Missing internal authentication headers"
    max_age = int(current_app.config.get("REALTIME_IDENTITY_MAX_AGE_SECONDS", 300))
    if not _validate_timestamp(timestamp, max_age):
        return None, "Invalid internal timestamp"
    if not _validate_nonce(nonce):
        return None, "Invalid internal nonce"
    return (timestamp, nonce, signature, max_age), None


def _authenticate_request(secret):
    credentials, error = _checked_auth_headers()
    if error:
        return None, error
    timestamp, nonce, signature, max_age = credentials
    raw_body = request.get_data(cache=True) or b""
    if not verify(secret, timestamp, nonce, raw_body, signature):
        return None, "Invalid internal signature"
    if not _remember_nonce(nonce, max_age):
        return None, "Internal request replayed"
    return raw_body, None


def _identity_payload(raw_body):
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, (jsonify({"error": "Invalid JSON body"}), 400)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "Invalid JSON body"}), 400)
    return payload, None


def _user_identity_response(payload):
    """Resolve live user/membership only after internal authentication."""
    user_id = _validate_user_id(payload)
    if user_id is None:
        return jsonify({"error": "Invalid user_id"}), 400

    user = _lookup_user(user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    membership = _lookup_membership(user_id)

    return (
        jsonify(
            {
                "user_id": user.id,
                "username": user.username,
                "active": True,
                "team_id": membership.team_id if membership else None,
                "role": membership.role if membership else None,
            }
        ),
        200,
    )


@realtime_internal_bp.route("/identity", methods=["POST"])
def identity():
    secret = str(current_app.config.get("REALTIME_HMAC_SECRET", "")).strip()
    if not secret:
        return jsonify({"error": "Realtime identity is not configured"}), 503
    raw_body, auth_error = _authenticate_request(secret)
    if auth_error:
        return _unauthorized(auth_error)
    payload, error = _identity_payload(raw_body)
    if error:
        return error
    return _user_identity_response(payload)
