import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models.user import User
from app.security import generate_token, hash_password


@pytest.fixture()
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _create_user(username, email, is_admin=False):
    user = User(
        username=username,
        email=email,
        password_hash=hash_password("secret123"),
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _headers_for(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


@pytest.fixture()
def auth_headers(app):
    """Usuario autenticado sin privilegios administrativos."""
    return _headers_for(_create_user("tester", "tester@example.com"))


@pytest.fixture()
def admin_headers(app):
    """Usuario administrador para escrituras del catálogo global."""
    return _headers_for(_create_user("admin", "admin@example.com", is_admin=True))
