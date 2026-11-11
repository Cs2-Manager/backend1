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


def _get_env_with_fallback(value_name, fallback):
    """Lee una variable de entorno con valor de respaldo."""
    return os.getenv(value_name) or fallback or ""


def _read_secret_file(path):
    """Lee un secreto desde un archivo. Devuelve cadena vacía si no existe."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _secret_env(value_name, file_name, default_file):
    """Lee un secreto desde la variable o desde un archivo privado.

    El archivo es la vía usada en Docker para compartir el secreto HMAC con el
    servicio realtime sin publicarlo en variables de entorno ni en imágenes.
    """
    direct = _get_env_with_fallback(value_name, "").strip()
    if direct:
        return direct
    path = _get_env_with_fallback(file_name, default_file or "").strip()
    if not path:
        return ""
    return _read_secret_file(path)


# SECRET_KEY debe tener al menos 32 bytes (RFC 7518 §3.2 para HMAC-SHA256).
# En producción se debe definir mediante la variable de entorno SECRET_KEY
# (o SECRET_KEY_FILE). Si falta o es demasiado corta, Flask no arranca.
# En desarrollo se permite un valor aleatorio temporal con advertencia.
# Nunca se usa un valor predecible ni se rotan secretos existentes
# automáticamente.
import secrets as _secrets
import warnings as _warnings


def _detect_environment() -> str:
    """Detecta el entorno de ejecución: 'production' o 'development'.

    Se inspecciona APP_ENV, FLASK_ENV y ENV (en ese orden). Cualquier valor
    que contenga 'production' o 'prod' se considera producción. Cualquier otro
    valor, o la ausencia de todas, se trata como desarrollo.
    """
    for var in ("APP_ENV", "FLASK_ENV", "ENV"):
        value = os.getenv(var, "").strip().lower()
        if value in ("production", "prod"):
            return "production"
        if value in ("development", "dev", "local"):
            return "development"
    return "development"


def _read_secret_file(path: str) -> str:
    """Lee un secreto desde un archivo. Devuelve cadena vacía si no existe."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _resolve_secret_key() -> str:
    """Resuelve SECRET_KEY con validación según el entorno.

    Orden de prioridad:
      1. Variable de entorno SECRET_KEY.
      2. Variable de entorno SECRET_KEY_FILE apuntando a un archivo.
    """
    env_value = os.getenv("SECRET_KEY", "").strip()

    if not env_value:
        secret_file = os.getenv("SECRET_KEY_FILE", "").strip()
        if secret_file:
            env_value = _read_secret_file(secret_file)

    environment = _detect_environment()

    if environment == "production":
        if not env_value:
            raise RuntimeError(
                "SECRET_KEY no está definida. En producción es obligatoria "
                "definirla mediante la variable de entorno SECRET_KEY o "
                "SECRET_KEY_FILE. No se usará un valor predeterminado."
            )
        if len(env_value.encode("utf-8")) < 32:
            raise RuntimeError(
                "SECRET_KEY tiene menos de 32 bytes (RFC 7518 §3.2). "
                "Configure una clave más larga en producción."
            )
        return env_value

    # Desarrollo: valor aleatorio si no está definida, advertencia si es corta.
    if not env_value:
        generated = _secrets.token_hex(32)
        _warnings.warn(
            "SECRET_KEY no está definida. Usando valor aleatorio temporal "
            "para desarrollo. No es persistente: definir SECRET_KEY en .env "
            "o SECRET_KEY_FILE.",
            stacklevel=2,
        )
        return generated

    if len(env_value.encode("utf-8")) < 32:
        _warnings.warn(
            "SECRET_KEY tiene menos de 32 bytes (RFC 7518 §3.2). "
            "Configure una clave más larga en producción.",
            stacklevel=2,
        )
    return env_value


class Config:
    SECRET_KEY = _resolve_secret_key()
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

    # Servicio de notificaciones en tiempo real (NestJS + Socket.IO). La API
    # interna solo se usa servidor-a-servidor: Flask firma cada evento con un
    # secreto exclusivo (nunca el SECRET_KEY de sesiones) y no publica la ruta
    # /internal/ a través de nginx.
    REALTIME_ENABLED = _as_bool(os.getenv("REALTIME_ENABLED"), default=True)
    REALTIME_URL = os.getenv("REALTIME_URL", "http://realtime:3000").rstrip("/")
    REALTIME_TIMEOUT_SECONDS = float(
        os.getenv("REALTIME_TIMEOUT_SECONDS", "2")
    )
    REALTIME_HMAC_SECRET = _secret_env(
        "REALTIME_HMAC_SECRET",
        "REALTIME_HMAC_SECRET_FILE",
        "/var/lib/cs2-matchmaking/realtime_hmac_secret",
    )
    REALTIME_IDENTITY_MAX_AGE_SECONDS = int(
        os.getenv("REALTIME_IDENTITY_MAX_AGE_SECONDS", "300")
    )
    # Outbox: reintentos con backoff acotado. El relay solo se arranca cuando
    # realtime está habilitado; en pruebas permanece apagado salvo activación
    # explícita para no crear hilos ni filas inesperadas.
    REALTIME_OUTBOX_RELAY_ENABLED = _as_bool(
        os.getenv("REALTIME_OUTBOX_RELAY_ENABLED"), default=True
    )
    REALTIME_OUTBOX_RELAY_INTERVAL_SECONDS = int(
        os.getenv("REALTIME_OUTBOX_RELAY_INTERVAL_SECONDS", "5")
    )
    REALTIME_OUTBOX_BATCH_SIZE = int(
        os.getenv("REALTIME_OUTBOX_BATCH_SIZE", "20")
    )
    REALTIME_OUTBOX_MAX_ATTEMPTS = int(
        os.getenv("REALTIME_OUTBOX_MAX_ATTEMPTS", "8")
    )
    REALTIME_OUTBOX_BACKOFF_BASE_SECONDS = float(
        os.getenv("REALTIME_OUTBOX_BACKOFF_BASE_SECONDS", "2")
    )
    REALTIME_OUTBOX_BACKOFF_MAX_SECONDS = float(
        os.getenv("REALTIME_OUTBOX_BACKOFF_MAX_SECONDS", "300")
    )

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

    # El servicio realtime se desactiva por defecto en pruebas: cada suite que
    # lo necesite levanta un receptor HTTP propio y habilita la publicación.
    REALTIME_ENABLED = False
    REALTIME_URL = "http://127.0.0.1:1"
    REALTIME_TIMEOUT_SECONDS = 1
    REALTIME_HMAC_SECRET = "testing-realtime-hmac-secret"
    REALTIME_IDENTITY_MAX_AGE_SECONDS = 300
    REALTIME_OUTBOX_RELAY_ENABLED = False
