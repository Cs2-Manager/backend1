"""Servicio de autenticación y usuarios."""

from app.errors import ApiError
from app.extensions import db
from app.models.user import User
from app.security import check_password, hash_password
from app.validators import clean_str, require_fields

REQUIRED_FIELDS = ("username", "email", "password")


def register_user(data):
    """Registra un usuario nuevo. Lanza ApiError si los datos no son válidos."""
    errors = require_fields(data, REQUIRED_FIELDS)
    if errors:
        raise ApiError("Missing required fields", status_code=400, fields=errors)

    username = clean_str(data["username"])
    email = clean_str(data["email"]).lower()

    if db.session.query(User.id).filter_by(username=username).first():
        raise ApiError("Username already exists", status_code=409)
    if db.session.query(User.id).filter_by(email=email).first():
        raise ApiError("Email already in use", status_code=409)

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(data["password"]),
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(identifier, password):
    """Valida credenciales y devuelve el usuario autenticado."""
    identifier = clean_str(identifier)
    if not identifier or not password:
        raise ApiError("Missing username/email or password", status_code=400)

    user = (
        db.session.query(User)
        .filter((User.username == identifier) | (User.email == identifier))
        .first()
    )
    if user is None or not check_password(password, user.password_hash):
        raise ApiError("Invalid credentials", status_code=401)
    return user
