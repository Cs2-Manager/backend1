from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.user import User
from app.security import check_password, generate_token, hash_password, jwt_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

REQUIRED_FIELDS = ("username", "email", "password")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing:
        return (
            jsonify({"error": "Missing required fields", "fields": missing}),
            400,
        )

    username = data["username"].strip()
    email = data["email"].strip().lower()

    if db.session.query(User.id).filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 409
    if db.session.query(User.id).filter_by(email=email).first():
        return jsonify({"error": "Email already in use"}), 409

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(data["password"]),
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(
        {"message": "User registered successfully", "user": user.to_dict()}
    ), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("username") or data.get("email") or "").strip()
    password = data.get("password", "")

    if not identifier or not password:
        return jsonify({"error": "Missing username/email or password"}), 400

    user = (
        db.session.query(User)
        .filter((User.username == identifier) | (User.email == identifier))
        .first()
    )

    if user is None or not check_password(password, user.password_hash):
        return jsonify({"error": "Invalid credentials"}), 401

    token = generate_token(user)
    return jsonify(
        {"token": token, "token_type": "Bearer", "user": user.to_dict()}
    ), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me(user):
    return jsonify({"user": user.to_dict()}), 200
