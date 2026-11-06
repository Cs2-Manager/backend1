"""Integración verificada con Steam.

Modelos separados de la identidad local:

- `SteamAccount`: vínculo único entre un `User` y un SteamID64.
- `SteamGameStats`: datos públicos que Steam Web API entrega para un juego.
- `SteamAuthRequest`: correlación de un único uso para el flujo OpenID.

No se guardan credenciales de Steam. Solo se persiste el SteamID64 y datos
públicos obtenidos de las APIs oficiales.
"""

from datetime import datetime, timezone

from app.extensions import db

STEAM_CS2_APP_ID = 730
STEAM_AUTH_INTENTS = ("LOGIN", "LINK")
STEAM_SYNC_STATUSES = ("NEVER", "OK", "PARTIAL", "ERROR")
STEAM_SOURCES = ("VERIFIED_STEAM", "UNAVAILABLE", "MANUAL")


def _utcnow():
    return datetime.now(timezone.utc)


class SteamAccount(db.Model):
    __tablename__ = "steam_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    steam_id = db.Column(
        db.String(20), nullable=False, unique=True, index=True
    )
    persona_name = db.Column(db.String(100), nullable=True)
    profile_url = db.Column(db.String(500), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    avatar_medium_url = db.Column(db.String(500), nullable=True)
    avatar_full_url = db.Column(db.String(500), nullable=True)
    persona_state = db.Column(db.Integer, nullable=True)
    community_visibility_state = db.Column(db.Integer, nullable=True)
    profile_created_at = db.Column(db.DateTime, nullable=True)
    last_logoff_at = db.Column(db.DateTime, nullable=True)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(
        db.String(20),
        nullable=False,
        default="NEVER",
        server_default="NEVER",
    )
    last_sync_error = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", back_populates="steam_account")
    game_stats = db.relationship(
        "SteamGameStats",
        back_populates="steam_account",
        cascade="all, delete-orphan",
    )

    def cs2_stats(self):
        for stat in self.game_stats:
            if stat.app_id == STEAM_CS2_APP_ID:
                return stat
        return None


class SteamGameStats(db.Model):
    __tablename__ = "steam_game_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "steam_account_id",
            "app_id",
            name="uq_steam_game_stats_account_app",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    steam_account_id = db.Column(
        db.Integer,
        db.ForeignKey("steam_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_id = db.Column(
        db.Integer,
        nullable=False,
        default=STEAM_CS2_APP_ID,
        server_default=str(STEAM_CS2_APP_ID),
    )
    name = db.Column(db.String(200), nullable=True)
    playtime_forever_minutes = db.Column(db.Integer, nullable=True)
    playtime_two_weeks_minutes = db.Column(db.Integer, nullable=True)
    last_played_at = db.Column(db.DateTime, nullable=True)
    icon_url = db.Column(db.String(500), nullable=True)
    source = db.Column(
        db.String(20),
        nullable=False,
        default="VERIFIED_STEAM",
        server_default="VERIFIED_STEAM",
    )
    fetched_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    steam_account = db.relationship("SteamAccount", back_populates="game_stats")


class SteamAuthRequest(db.Model):
    __tablename__ = "steam_auth_requests"

    id = db.Column(db.Integer, primary_key=True)
    state_hash = db.Column(
        db.String(64), nullable=False, unique=True, index=True
    )
    handoff_hash = db.Column(
        db.String(64), nullable=True, unique=True, index=True
    )
    intent = db.Column(db.String(10), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    return_to = db.Column(db.String(500), nullable=False)
    steam_id = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    handoff_expires_at = db.Column(db.DateTime, nullable=True)
    handoff_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])
