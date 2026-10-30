from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import current_app, jsonify, request

from app.models.user import User
from app.permissions.policies import is_admin


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_token(user, expires_delta=None):
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + (
            expires_delta or timedelta(hours=current_app.config["JWT_EXPIRATION_HOURS"])
        ),
    }
    return jwt.encode(
        payload,
        current_app.config["SECRET_KEY"],
        algorithm=current_app.config["JWT_ALGORITHM"],
    )


def decode_token(token):
    return jwt.decode(
        token,
        current_app.config["SECRET_KEY"],
        algorithms=[current_app.config["JWT_ALGORITHM"]],
    )


def get_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1]


def _auth_error(message):
    return jsonify({"error": message}), 401


def _resolve_user():
    """Devuelve (usuario, respuesta_de_error)."""
    token = get_token()
    if token is None:
        return None, _auth_error("Missing or invalid Authorization header")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        return None, _auth_error("Token has expired")
    except jwt.InvalidTokenError:
        return None, _auth_error("Invalid token")

    user = db_session_get_user(payload)
    if user is None:
        return None, _auth_error("User not found")
    return user, None


def jwt_required():
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user, error = _resolve_user()
            if error is not None:
                return error
            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def jwt_optional():
    """Autentica si hay token; permite continuar como anónimo si no lo hay."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if get_token() is None:
                return view(None, *args, **kwargs)
            user, error = _resolve_user()
            if error is not None:
                return error
            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def admin_required():
    """Exige JWT válido y `is_admin=True` en la base de datos."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user, error = _resolve_user()
            if error is not None:
                return error
            if not is_admin(user):
                return jsonify({"error": "Administrator access required"}), 403
            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def db_session_get_user(payload):
    from app.extensions import db

    user_id = payload.get("sub")
    return db.session.get(User, user_id)
