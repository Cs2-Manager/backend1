from flask import Blueprint, jsonify, request

from app.security import generate_token, jwt_required
from app.services import auth_service

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    user = auth_service.register_user(data)
    return (
        jsonify({"message": "User registered successfully", "user": user.to_dict()}),
        201,
    )


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    identifier = data.get("username") or data.get("email") or ""
    user = auth_service.authenticate(identifier, data.get("password", ""))
    token = generate_token(user)
    return (
        jsonify({"token": token, "token_type": "Bearer", "user": user.to_dict()}),
        200,
    )


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me(user):
    return jsonify({"user": user.to_dict()}), 200
