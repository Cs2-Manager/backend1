from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import current_app, jsonify, request

from app.models.user import User


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


def jwt_required():
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            token = get_token()
            if token is None:
                return jsonify(
                    {"error": "Missing or invalid Authorization header"}
                ), 401
            try:
                payload = decode_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token has expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid token"}), 401

            user = db_session_get_user(payload)
            if user is None:
                return jsonify({"error": "User not found"}), 401
            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def db_session_get_user(payload):
    from app.extensions import db

    user_id = payload.get("sub")
    return db.session.get(User, user_id)
