"""Integración con FACEIT Data API v4 y FACEIT Connect.

Los datos de FACEIT viven en tablas propias y nunca se mezclan con Steam ni
con las estadísticas manuales o de demos. Reglas de diseño:

- `FaceitAccount` es el vínculo único entre un `User` y un `player_id` de
  FACEIT. `link_status` distingue una cuenta descubierta por SteamID de una
  cuenta verificada mediante OAuth2 con PKCE.
- `FaceitPlayerStats` guarda el último agregado de por vida reportado por la
  API. Cada métrica es nullable: FACEIT no garantiza todas las claves.
- `FaceitMatch` y `FaceitMatchPlayerStats` preservan el historial sin crear
  duplicados al re-sincronizar (`account_id` + `faceit_match_id` único).
- `FaceitMapStats` mantiene agregados por mapa calculados solo con partidas
  verificadas.
- `FaceitEloSnapshot` registra únicamente valores reales observados; el
  gráfico nunca reconstruye ELO histórico que la API no entregó.
- `FaceitSyncState` coordina sincronizaciones concurrentes con un lease y
  conserva el backoff ante errores temporales.
- `FaceitOAuthRequest` correlaciona el flujo OAuth2 de un solo uso. El
  `code_verifier` PKCE se guarda cifrado y nunca se serializa.
"""

from datetime import datetime, timezone

from app.extensions import db

FACEIT_GAME_ID = "cs2"
FACEIT_LINK_STATUSES = ("DISCOVERED", "VERIFIED")
FACEIT_VERIFICATION_SOURCES = ("STEAM_DISCOVERY", "OAUTH2")
FACEIT_SYNC_STATUSES = (
    "NEVER",
    "OK",
    "PARTIAL",
    "ERROR",
    "SKIPPED",
    "NOT_CONFIGURED",
)
FACEIT_MATCH_STATUSES = ("OK", "PARTIAL", "UNAVAILABLE")
FACEIT_SOURCES = ("VERIFIED_FACEIT", "UNAVAILABLE")


def _utcnow():
    return datetime.now(timezone.utc)


class FaceitAccount(db.Model):
    __tablename__ = "faceit_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    faceit_player_id = db.Column(
        db.String(64), nullable=False, unique=True, index=True
    )
    nickname = db.Column(db.String(100), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    cover_image_url = db.Column(db.String(500), nullable=True)
    country = db.Column(db.String(8), nullable=True)
    region = db.Column(db.String(20), nullable=True)
    steam_id = db.Column(db.String(20), nullable=True, index=True)
    steam_nickname = db.Column(db.String(100), nullable=True)
    faceit_url = db.Column(db.String(500), nullable=True)
    skill_level = db.Column(db.Integer, nullable=True)
    elo = db.Column(db.Integer, nullable=True)
    link_status = db.Column(
        db.String(20),
        nullable=False,
        default="DISCOVERED",
        server_default="DISCOVERED",
    )
    verification_source = db.Column(
        db.String(20),
        nullable=False,
        default="STEAM_DISCOVERY",
        server_default="STEAM_DISCOVERY",
    )
    verified_at = db.Column(db.DateTime, nullable=True)
    sync_enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default="true"
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", back_populates="faceit_account")
    stats = db.relationship(
        "FaceitPlayerStats",
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    matches = db.relationship(
        "FaceitMatch",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="FaceitMatch.played_at.desc()",
    )
    map_stats = db.relationship(
        "FaceitMapStats",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    elo_snapshots = db.relationship(
        "FaceitEloSnapshot",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="FaceitEloSnapshot.captured_at",
    )
    sync_state = db.relationship(
        "FaceitSyncState",
        back_populates="account",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def verified(self):
        return (
            self.link_status == "VERIFIED"
            and self.verification_source == "OAUTH2"
        )


class FaceitPlayerStats(db.Model):
    __tablename__ = "faceit_player_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "account_id", name="uq_faceit_player_stats_account"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game_id = db.Column(
        db.String(20),
        nullable=False,
        default=FACEIT_GAME_ID,
        server_default=FACEIT_GAME_ID,
    )
    matches_played = db.Column(db.Integer, nullable=True)
    wins = db.Column(db.Integer, nullable=True)
    losses = db.Column(db.Integer, nullable=True)
    win_rate = db.Column(db.Float, nullable=True)
    kills = db.Column(db.Integer, nullable=True)
    deaths = db.Column(db.Integer, nullable=True)
    assists = db.Column(db.Integer, nullable=True)
    kd = db.Column(db.Float, nullable=True)
    kr = db.Column(db.Float, nullable=True)
    headshots = db.Column(db.Integer, nullable=True)
    headshot_percentage = db.Column(db.Float, nullable=True)
    adr = db.Column(db.Float, nullable=True)
    mvps = db.Column(db.Integer, nullable=True)
    triple_kills = db.Column(db.Integer, nullable=True)
    quadruple_kills = db.Column(db.Integer, nullable=True)
    penta_kills = db.Column(db.Integer, nullable=True)
    rounds_played = db.Column(db.Integer, nullable=True)
    total_damage = db.Column(db.Integer, nullable=True)
    source = db.Column(
        db.String(20),
        nullable=False,
        default="VERIFIED_FACEIT",
        server_default="VERIFIED_FACEIT",
    )
    fetched_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    account = db.relationship("FaceitAccount", back_populates="stats")


class FaceitMatch(db.Model):
    __tablename__ = "faceit_matches"
    __table_args__ = (
        db.UniqueConstraint(
            "account_id",
            "faceit_match_id",
            name="uq_faceit_matches_account_match",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    faceit_match_id = db.Column(db.String(64), nullable=False, index=True)
    played_at = db.Column(db.DateTime, nullable=True, index=True)
    game_mode = db.Column(db.String(60), nullable=True)
    map_name = db.Column(db.String(80), nullable=True, index=True)
    region = db.Column(db.String(20), nullable=True)
    competition_name = db.Column(db.String(160), nullable=True)
    result = db.Column(db.String(10), nullable=True, index=True)
    team_score = db.Column(db.Integer, nullable=True)
    opponent_score = db.Column(db.Integer, nullable=True)
    score = db.Column(db.String(40), nullable=True)
    player_team_name = db.Column(db.String(120), nullable=True)
    opponent_team_name = db.Column(db.String(120), nullable=True)
    faceit_url = db.Column(db.String(500), nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="PARTIAL",
        server_default="PARTIAL",
    )
    source = db.Column(
        db.String(20),
        nullable=False,
        default="VERIFIED_FACEIT",
        server_default="VERIFIED_FACEIT",
    )
    fetched_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    account = db.relationship("FaceitAccount", back_populates="matches")
    player_stats = db.relationship(
        "FaceitMatchPlayerStats",
        back_populates="match",
        cascade="all, delete-orphan",
        uselist=False,
    )


class FaceitMatchPlayerStats(db.Model):
    __tablename__ = "faceit_match_player_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "match_id", name="uq_faceit_match_player_stats_match"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kills = db.Column(db.Integer, nullable=True)
    deaths = db.Column(db.Integer, nullable=True)
    assists = db.Column(db.Integer, nullable=True)
    kd = db.Column(db.Float, nullable=True)
    kr = db.Column(db.Float, nullable=True)
    adr = db.Column(db.Float, nullable=True)
    headshot_percentage = db.Column(db.Float, nullable=True)
    mvps = db.Column(db.Integer, nullable=True)
    rounds_played = db.Column(db.Integer, nullable=True)
    source = db.Column(
        db.String(20),
        nullable=False,
        default="VERIFIED_FACEIT",
        server_default="VERIFIED_FACEIT",
    )
    fetched_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    match = db.relationship("FaceitMatch", back_populates="player_stats")


class FaceitMapStats(db.Model):
    __tablename__ = "faceit_map_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "account_id", "map_name", name="uq_faceit_map_stats_account_map"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    map_name = db.Column(db.String(80), nullable=False, index=True)
    matches_played = db.Column(db.Integer, nullable=True)
    wins = db.Column(db.Integer, nullable=True)
    losses = db.Column(db.Integer, nullable=True)
    win_rate = db.Column(db.Float, nullable=True)
    kills = db.Column(db.Integer, nullable=True)
    deaths = db.Column(db.Integer, nullable=True)
    assists = db.Column(db.Integer, nullable=True)
    kd = db.Column(db.Float, nullable=True)
    adr = db.Column(db.Float, nullable=True)
    headshot_percentage = db.Column(db.Float, nullable=True)
    source = db.Column(
        db.String(20),
        nullable=False,
        default="VERIFIED_FACEIT",
        server_default="VERIFIED_FACEIT",
    )
    calculated_from = db.Column(
        db.String(20),
        nullable=False,
        default="FACEIT_SEGMENT",
        server_default="FACEIT_SEGMENT",
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    account = db.relationship("FaceitAccount", back_populates="map_stats")


class FaceitEloSnapshot(db.Model):
    __tablename__ = "faceit_elo_snapshots"
    __table_args__ = (
        db.UniqueConstraint(
            "account_id",
            "captured_at",
            name="uq_faceit_elo_snapshots_account_time",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    elo = db.Column(db.Integer, nullable=False)
    skill_level = db.Column(db.Integer, nullable=True)
    captured_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    source = db.Column(
        db.String(30),
        nullable=False,
        default="VERIFIED_FACEIT",
        server_default="VERIFIED_FACEIT",
    )

    account = db.relationship("FaceitAccount", back_populates="elo_snapshots")


class FaceitSyncState(db.Model):
    __tablename__ = "faceit_sync_states"
    __table_args__ = (
        db.UniqueConstraint(
            "account_id", name="uq_faceit_sync_states_account"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("faceit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="NEVER",
        server_default="NEVER",
    )
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    last_success_at = db.Column(db.DateTime, nullable=True)
    next_sync_at = db.Column(db.DateTime, nullable=True, index=True)
    consecutive_failures = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    last_error = db.Column(db.String(300), nullable=True)
    lease_until = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    account = db.relationship("FaceitAccount", back_populates="sync_state")


class FaceitOAuthRequest(db.Model):
    __tablename__ = "faceit_oauth_requests"

    id = db.Column(db.Integer, primary_key=True)
    state_hash = db.Column(
        db.String(64), nullable=False, unique=True, index=True
    )
    code_verifier_encrypted = db.Column(db.Text, nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    return_to = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])
