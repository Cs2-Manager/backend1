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
    # El frontend servido por nginx usa el MISMO origen que la API: el navegador
    # no genera solicitudes CORS. Esto queda para consumidores externos.
    CORS_ORIGINS: ClassVar[list] = _split_env(
        "CORS_ORIGINS", ["http://localhost", "http://127.0.0.1"]
    )
    CORS_SUPPORTS_CREDENTIALS: ClassVar[bool] = False
    JSON_SORT_KEYS = False

    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    # Integración con Steam. La API key vive exclusivamente en el backend y
    # nunca se serializa hacia el frontend.
    STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
    STEAM_PUBLIC_BASE_URL = os.getenv(
        "STEAM_PUBLIC_BASE_URL", "http://localhost"
    ).rstrip("/")
    STEAM_SYNC_MIN_INTERVAL_SECONDS = int(
        os.getenv("STEAM_SYNC_MIN_INTERVAL_SECONDS", "300")
    )
    STEAM_API_TIMEOUT_SECONDS = float(
        os.getenv("STEAM_API_TIMEOUT_SECONDS", "10")
    )
    STEAM_OPENID_TIMEOUT_SECONDS = float(
        os.getenv("STEAM_OPENID_TIMEOUT_SECONDS", "10")
    )
    STEAM_AUTH_REQUEST_TTL_SECONDS = int(
        os.getenv("STEAM_AUTH_REQUEST_TTL_SECONDS", "600")
    )
    STEAM_HANDOFF_TTL_SECONDS = int(
        os.getenv("STEAM_HANDOFF_TTL_SECONDS", "120")
    )
    STEAM_CS2_APP_ID = 730

    # Estadísticas de matchmaking oficial de CS2 (demos). No usan la Steam Web
    # API: el worker parsea demos que el jugador autoriza y aporta.
    MATCHMAKING_ENABLED = _as_bool(
        os.getenv("MATCHMAKING_ENABLED"), default=True
    )
    MATCHMAKING_STORAGE_DIR = os.getenv(
        "MATCHMAKING_STORAGE_DIR",
        os.path.join(BASE_DIR, "instance", "matchmaking"),
    )
    MATCHMAKING_INBOX_DIR = os.getenv(
        "MATCHMAKING_INBOX_DIR",
        os.path.join(
            os.getenv(
                "MATCHMAKING_STORAGE_DIR",
                os.path.join(BASE_DIR, "instance", "matchmaking"),
            ),
            "inbox",
        ),
    )
    MATCHMAKING_MAX_UPLOAD_MB = int(
        os.getenv("MATCHMAKING_MAX_UPLOAD_MB", "512")
    )
    MATCHMAKING_MAX_ATTEMPTS = int(
        os.getenv("MATCHMAKING_MAX_ATTEMPTS", "3")
    )
    MATCHMAKING_SYNC_MIN_INTERVAL_SECONDS = int(
        os.getenv("MATCHMAKING_SYNC_MIN_INTERVAL_SECONDS", "300")
    )
    MATCHMAKING_DISCOVERY_INTERVAL_SECONDS = int(
        os.getenv("MATCHMAKING_DISCOVERY_INTERVAL_SECONDS", "3600")
    )
    MATCHMAKING_DISCOVERY_MAX_CODES = int(
        os.getenv("MATCHMAKING_DISCOVERY_MAX_CODES", "50")
    )
    MATCHMAKING_WORKER_POLL_SECONDS = int(
        os.getenv("MATCHMAKING_WORKER_POLL_SECONDS", "15")
    )
    # Días tras los cuales una partida sin demo se marca como no disponible.
    MATCHMAKING_DEMO_EXPIRY_DAYS = int(
        os.getenv("MATCHMAKING_DEMO_EXPIRY_DAYS", "31")
    )
    MATCHMAKING_API_TIMEOUT_SECONDS = float(
        os.getenv("MATCHMAKING_API_TIMEOUT_SECONDS", "15")
    )
    # Clave de cifrado del game authentication code. Si no se define, se deriva
    # del SECRET_KEY de la aplicación.
    MATCHMAKING_SECRET_KEY = os.getenv("MATCHMAKING_SECRET_KEY") or SECRET_KEY

    # FACEIT Data API v4. La API key y el client secret viven exclusivamente en
    # el backend; nunca se serializan ni se escriben en logs.
    FACEIT_ENABLED = _as_bool(os.getenv("FACEIT_ENABLED"), default=True)
    FACEIT_API_KEY = os.getenv("FACEIT_API_KEY", "")
    FACEIT_API_BASE_URL = os.getenv(
        "FACEIT_API_BASE_URL", "https://open.faceit.com/data/v4"
    ).rstrip("/")
    FACEIT_API_TIMEOUT_SECONDS = float(
        os.getenv("FACEIT_API_TIMEOUT_SECONDS", "10")
    )
    FACEIT_API_MAX_RETRIES = int(os.getenv("FACEIT_API_MAX_RETRIES", "2"))
    FACEIT_API_BACKOFF_BASE_SECONDS = float(
        os.getenv("FACEIT_API_BACKOFF_BASE_SECONDS", "0.5")
    )
    FACEIT_CACHE_TTL_SECONDS = int(
        os.getenv("FACEIT_CACHE_TTL_SECONDS", "60")
    )
    FACEIT_HISTORY_DAYS = int(os.getenv("FACEIT_HISTORY_DAYS", "30"))
    FACEIT_HISTORY_LIMIT = int(os.getenv("FACEIT_HISTORY_LIMIT", "100"))
    FACEIT_HISTORY_MAX_PAGES = int(os.getenv("FACEIT_HISTORY_MAX_PAGES", "3"))
    FACEIT_SYNC_INTERVAL_SECONDS = int(
        os.getenv("FACEIT_SYNC_INTERVAL_SECONDS", "1800")
    )
    FACEIT_SYNC_MIN_INTERVAL_SECONDS = int(
        os.getenv("FACEIT_SYNC_MIN_INTERVAL_SECONDS", "300")
    )
    FACEIT_SYNC_BATCH_SIZE = int(os.getenv("FACEIT_SYNC_BATCH_SIZE", "5"))
    FACEIT_SYNC_LEASE_SECONDS = int(
        os.getenv("FACEIT_SYNC_LEASE_SECONDS", "600")
    )
    # Origen exacto con el que el navegador abre la SPA. Se usa para volver al
    # perfil después del callback OAuth2.
    FACEIT_PUBLIC_BASE_URL = os.getenv(
        "FACEIT_PUBLIC_BASE_URL",
        os.getenv("STEAM_PUBLIC_BASE_URL", "http://localhost"),
    ).rstrip("/")
    # FACEIT Connect (OAuth2 Authorization Code + PKCE). Si falta cualquier
    # credencial, la vinculación verificada queda como NOT_CONFIGURED y la
    # consulta pública por SteamID sigue disponible.
    FACEIT_OAUTH_CLIENT_ID = os.getenv("FACEIT_OAUTH_CLIENT_ID", "")
    FACEIT_OAUTH_CLIENT_SECRET = os.getenv("FACEIT_OAUTH_CLIENT_SECRET", "")
    FACEIT_OAUTH_REDIRECT_URI = os.getenv(
        "FACEIT_OAUTH_REDIRECT_URI", ""
    )
    FACEIT_OAUTH_AUTHORIZE_URL = os.getenv(
        "FACEIT_OAUTH_AUTHORIZE_URL", "https://accounts.faceit.com"
    )
    FACEIT_OAUTH_TOKEN_URL = os.getenv(
        "FACEIT_OAUTH_TOKEN_URL",
        "https://api.faceit.com/auth/v1/oauth/token",
    )
    FACEIT_OAUTH_USERINFO_URL = os.getenv(
        "FACEIT_OAUTH_USERINFO_URL",
        "https://api.faceit.com/auth/v1/resources/userinfo",
    )
    # Debe coincidir con los scopes habilitados en el cliente OAuth2 de FACEIT.
    # `email` solo se agrega si el cliente lo tiene concedido en el portal.
    FACEIT_OAUTH_SCOPES = os.getenv(
        "FACEIT_OAUTH_SCOPES", "openid profile membership"
    )
    FACEIT_OAUTH_TIMEOUT_SECONDS = float(
        os.getenv("FACEIT_OAUTH_TIMEOUT_SECONDS", "10")
    )
    FACEIT_OAUTH_REQUEST_TTL_SECONDS = int(
        os.getenv("FACEIT_OAUTH_REQUEST_TTL_SECONDS", "600")
    )
    # Clave para cifrar el code_verifier PKCE en reposo. Si no se define, se
    # deriva del SECRET_KEY general.
    FACEIT_SECRET_KEY = os.getenv("FACEIT_SECRET_KEY") or SECRET_KEY


class TestingConfig(Config):
    """Configuración para tests: SQLite en memoria y sin comprobaciones externas."""

    TESTING = True
    SECRET_KEY = "testing-secret-key-with-at-least-32-bytes!!"
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    } if SQLALCHEMY_DATABASE_URI.startswith("sqlite") else {"pool_pre_ping": True}
    STEAM_API_KEY = "testing-steam-api-key"
    STEAM_PUBLIC_BASE_URL = "http://localhost"
    STEAM_SYNC_MIN_INTERVAL_SECONDS = 300
    STEAM_API_TIMEOUT_SECONDS = 2
    STEAM_OPENID_TIMEOUT_SECONDS = 2
    STEAM_AUTH_REQUEST_TTL_SECONDS = 600
    STEAM_HANDOFF_TTL_SECONDS = 120

    MATCHMAKING_ENABLED = True
    MATCHMAKING_STORAGE_DIR = os.path.join(
        os.getenv("TMPDIR", "/tmp"), "cs2_manager_matchmaking_test"
    )
    MATCHMAKING_INBOX_DIR = os.path.join(
        MATCHMAKING_STORAGE_DIR, "inbox"
    )
    MATCHMAKING_MAX_UPLOAD_MB = 8
    MATCHMAKING_MAX_ATTEMPTS = 2
    MATCHMAKING_SYNC_MIN_INTERVAL_SECONDS = 300
    MATCHMAKING_DISCOVERY_INTERVAL_SECONDS = 3600
    MATCHMAKING_DISCOVERY_MAX_CODES = 10
    MATCHMAKING_WORKER_POLL_SECONDS = 1
    MATCHMAKING_DEMO_EXPIRY_DAYS = 31
    MATCHMAKING_API_TIMEOUT_SECONDS = 1
    MATCHMAKING_SECRET_KEY = "testing-matchmaking-secret-key"

    FACEIT_ENABLED = True
    FACEIT_API_KEY = "testing-faceit-api-key"
    FACEIT_API_BASE_URL = "https://faceit.test/data/v4"
    FACEIT_API_TIMEOUT_SECONDS = 1
    FACEIT_API_MAX_RETRIES = 0
    FACEIT_API_BACKOFF_BASE_SECONDS = 0
    FACEIT_CACHE_TTL_SECONDS = 0
    FACEIT_HISTORY_DAYS = 30
    FACEIT_HISTORY_LIMIT = 100
    FACEIT_HISTORY_MAX_PAGES = 2
    FACEIT_SYNC_INTERVAL_SECONDS = 1800
    FACEIT_SYNC_MIN_INTERVAL_SECONDS = 0
    FACEIT_SYNC_BATCH_SIZE = 5
    FACEIT_SYNC_LEASE_SECONDS = 600
    FACEIT_PUBLIC_BASE_URL = "http://localhost"
    FACEIT_OAUTH_CLIENT_ID = "testing-faceit-client"
    FACEIT_OAUTH_CLIENT_SECRET = "testing-faceit-secret"
    FACEIT_OAUTH_REDIRECT_URI = (
        "http://localhost/api/faceit/oauth/callback"
    )
    FACEIT_OAUTH_AUTHORIZE_URL = "https://accounts.faceit.test"
    FACEIT_OAUTH_TOKEN_URL = "https://api.faceit.test/auth/v1/oauth/token"
    FACEIT_OAUTH_USERINFO_URL = (
        "https://api.faceit.test/auth/v1/resources/userinfo"
    )
    FACEIT_OAUTH_SCOPES = "openid profile membership"
    FACEIT_OAUTH_TIMEOUT_SECONDS = 1
    FACEIT_OAUTH_REQUEST_TTL_SECONDS = 600
    FACEIT_SECRET_KEY = "testing-faceit-secret-key"
