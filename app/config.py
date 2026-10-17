import os
from typing import ClassVar

from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _split_env(name, default):
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEBUG = _as_bool(os.getenv("DEBUG"), default=False)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # URL sin +driver para que SQLAlchemy use el instalado (psycopg2-binary)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://cs2_manager:cs2_manager_dev@db:5432/cs2_manager",
    )
    # Forzar configuración del motor para que funcione con psycopg2-binary
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # Orígenes permitidos por CORS (configurable por env, separado por comas).
    CORS_ORIGINS: ClassVar[list] = _split_env(
        "CORS_ORIGINS", ["http://localhost", "http://127.0.0.1"]
    )
    CORS_SUPPORTS_CREDENTIALS: ClassVar[bool] = False
    JSON_SORT_KEYS = False

    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))


class TestingConfig(Config):
    """Configuración para tests: SQLite en memoria y sin comprobaciones externas."""

    TESTING = True
    SECRET_KEY = "testing-secret-key-with-at-least-32-bytes!!"
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
