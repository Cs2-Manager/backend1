"""Estadísticas de matchmaking oficial de CS2 a partir de demos.

Separado de `SteamAccount` (identidad y playtime) y de los datos manuales del
perfil. Nada de este módulo se obtiene de la Steam Web API: todas las métricas
salen de demos autorizadas por el jugador y procesadas por el worker.

- `MatchmakingAuthorization`: permiso revocable con el *game authentication
  code* cifrado y el cursor de descubrimiento.
- `MatchmakingMatch`: partida oficial con sus estadísticas individuales.
- `MatchmakingMapStats`: agregados por mapa recalculados tras cada demo.
- `MatchmakingDemoJob`: cola de demos con deduplicación y reintentos.
- `MatchmakingSyncRun`: historial de descubrimientos/procesamientos.
"""

from datetime import datetime, timezone

from app.extensions import db

MATCHMAKING_AUTH_STATUSES = ("DISABLED", "ACTIVE", "REVOKED", "INVALID")
MATCHMAKING_DEMO_STATUSES = (
    "AWAITING_DEMO",
    "QUEUED",
    "PROCESSING",
    "OK",
    "ERROR",
    "UNAVAILABLE",
    "DUPLICATE",
)
MATCHMAKING_JOB_STATUSES = ("QUEUED", "PROCESSING", "OK", "ERROR", "DUPLICATE")
MATCHMAKING_RESULTS = ("WIN", "LOSS", "DRAW", "UNKNOWN")
MATCHMAKING_SYNC_KINDS = ("DISCOVERY", "PROCESSING", "MANUAL")
MATCHMAKING_SYNC_STATUSES = ("RUNNING", "OK", "PARTIAL", "ERROR")
MATCHMAKING_SOURCES = ("VERIFIED_DEMO", "PENDING", "UNAVAILABLE", "INCOMPLETE")


def _utcnow():
    return datetime.now(timezone.utc)


class MatchmakingAuthorization(db.Model):
    __tablename__ = "matchmaking_authorizations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    steam_id = db.Column(db.String(20), nullable=False)
    # Cifrado simétrico (Fernet). Nunca se serializa ni se registra en logs.
    auth_code_encrypted = db.Column(db.Text, nullable=True)
    first_share_code = db.Column(db.String(80), nullable=True)
    cursor_share_code = db.Column(db.String(80), nullable=True)
    status = db.Column(
        db.String(10),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
    )
    authorized_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)
    last_discovery_at = db.Column(db.DateTime, nullable=True)
    last_discovery_status = db.Column(db.String(20), nullable=True)
    last_discovery_error = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", back_populates="matchmaking_authorization")
    matches = db.relationship(
        "MatchmakingMatch", back_populates="authorization"
    )


class MatchmakingMatch(db.Model):
    __tablename__ = "matchmaking_matches"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "share_code",
            name="uq_matchmaking_matches_user_share_code",
        ),
        db.UniqueConstraint(
            "user_id",
            "match_id",
            name="uq_matchmaking_matches_user_match_id",
        ),
        db.UniqueConstraint(
            "user_id",
            "demo_sha256",
            name="uq_matchmaking_matches_user_demo_sha",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authorization_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "matchmaking_authorizations.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    share_code = db.Column(db.String(80), nullable=True)
    match_id = db.Column(db.BigInteger, nullable=True)
    map_name = db.Column(db.String(80), nullable=True)
    played_at = db.Column(db.DateTime, nullable=True)
    result = db.Column(
        db.String(10),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )
    team_score = db.Column(db.Integer, nullable=True)
    opponent_score = db.Column(db.Integer, nullable=True)
    rounds_played = db.Column(db.Integer, nullable=False, default=0)
    rounds_won = db.Column(db.Integer, nullable=False, default=0)
    rounds_lost = db.Column(db.Integer, nullable=False, default=0)
    kills = db.Column(db.Integer, nullable=False, default=0)
    deaths = db.Column(db.Integer, nullable=False, default=0)
    assists = db.Column(db.Integer, nullable=False, default=0)
    damage = db.Column(db.Integer, nullable=False, default=0)
    headshot_kills = db.Column(db.Integer, nullable=False, default=0)
    mvps = db.Column(db.Integer, nullable=False, default=0)
    clutches = db.Column(db.Integer, nullable=False, default=0)
    opening_kills = db.Column(db.Integer, nullable=False, default=0)
    opening_deaths = db.Column(db.Integer, nullable=False, default=0)
    kast_rounds = db.Column(db.Integer, nullable=False, default=0)
    adr = db.Column(db.Numeric(6, 1), nullable=True)
    hs_percentage = db.Column(db.Numeric(5, 1), nullable=True)
    kd = db.Column(db.Numeric(6, 2), nullable=True)
    kast_percentage = db.Column(db.Numeric(5, 1), nullable=True)
    demo_status = db.Column(
        db.String(20),
        nullable=False,
        default="AWAITING_DEMO",
        server_default="AWAITING_DEMO",
        index=True,
    )
    demo_sha256 = db.Column(db.String(64), nullable=True)
    demo_path = db.Column(db.String(500), nullable=True)
    processing_error = db.Column(db.String(300), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    processed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", back_populates="matchmaking_matches")
    authorization = db.relationship(
        "MatchmakingAuthorization", back_populates="matches"
    )
    job = db.relationship(
        "MatchmakingDemoJob", back_populates="match", uselist=False
    )


class MatchmakingMapStats(db.Model):
    __tablename__ = "matchmaking_map_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "map_name", name="uq_matchmaking_map_stats_user_map"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    map_name = db.Column(db.String(80), nullable=False)
    matches = db.Column(db.Integer, nullable=False, default=0)
    wins = db.Column(db.Integer, nullable=False, default=0)
    losses = db.Column(db.Integer, nullable=False, default=0)
    draws = db.Column(db.Integer, nullable=False, default=0)
    rounds_played = db.Column(db.Integer, nullable=False, default=0)
    kills = db.Column(db.Integer, nullable=False, default=0)
    deaths = db.Column(db.Integer, nullable=False, default=0)
    assists = db.Column(db.Integer, nullable=False, default=0)
    damage = db.Column(db.Integer, nullable=False, default=0)
    headshot_kills = db.Column(db.Integer, nullable=False, default=0)
    kast_rounds = db.Column(db.Integer, nullable=False, default=0)
    mvps = db.Column(db.Integer, nullable=False, default=0)
    clutches = db.Column(db.Integer, nullable=False, default=0)
    opening_kills = db.Column(db.Integer, nullable=False, default=0)
    opening_deaths = db.Column(db.Integer, nullable=False, default=0)
    adr = db.Column(db.Numeric(6, 1), nullable=True)
    hs_percentage = db.Column(db.Numeric(5, 1), nullable=True)
    kd = db.Column(db.Numeric(6, 2), nullable=True)
    kast_percentage = db.Column(db.Numeric(5, 1), nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MatchmakingDemoJob(db.Model):
    __tablename__ = "matchmaking_demo_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_id = db.Column(
        db.Integer,
        db.ForeignKey("matchmaking_matches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_path = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(255), nullable=True)
    sha256 = db.Column(db.String(64), nullable=False, unique=True, index=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="QUEUED",
        server_default="QUEUED",
        index=True,
    )
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    match = db.relationship("MatchmakingMatch", back_populates="job")


class MatchmakingSyncRun(db.Model):
    __tablename__ = "matchmaking_sync_runs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = db.Column(db.String(20), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="RUNNING",
        server_default="RUNNING",
    )
    found = db.Column(db.Integer, nullable=False, default=0)
    processed = db.Column(db.Integer, nullable=False, default=0)
    failed = db.Column(db.Integer, nullable=False, default=0)
    message = db.Column(db.String(300), nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
