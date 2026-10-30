"""Perfil competitivo, estadísticas e historial de jugador.

La identidad de cuenta sigue viviendo en `User`. Este módulo agrega la capa
competitiva y mantiene separadas las responsabilidades:

- `PlayerProfile`: identidad pública del jugador.
- `PlayerCompetitiveProfile`: datos de clasificación (solo con fuente real).
- `PlayerStats`: agregados globales de partidas registradas.
- `PlayerMatch`: historial de partidas reales.
- `PlayerMapStats`: agregados por mapa.
- `PlayerSocialLink`: enlaces sociales opcionales.
"""

from datetime import datetime, timezone

from app.extensions import db

PROFILE_VISIBILITIES = ("PUBLIC", "PRIVATE")
SOCIAL_PLATFORMS = ("twitch", "youtube", "x", "instagram", "discord")
COMPETITIVE_STATUSES = ("UNRANKED", "RANKED", "INACTIVE")
MATCH_RESULTS = ("WIN", "LOSS", "DRAW")
MATCH_TYPES = ("COMPETITIVE", "PRACTICE", "OTHER")


def _utcnow():
    return datetime.now(timezone.utc)


class PlayerProfile(db.Model):
    __tablename__ = "player_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    nickname = db.Column(
        db.String(80), nullable=False, unique=True, index=True
    )
    display_name = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(2), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    steam_url = db.Column(db.String(500), nullable=True)
    visibility = db.Column(
        db.String(10),
        nullable=False,
        default="PRIVATE",
        server_default="PRIVATE",
    )
    last_active_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", back_populates="profile")
    social_links = db.relationship(
        "PlayerSocialLink",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="PlayerSocialLink.platform",
    )
    competitive = db.relationship(
        "PlayerCompetitiveProfile",
        back_populates="profile",
        cascade="all, delete-orphan",
        uselist=False,
    )
    stats = db.relationship(
        "PlayerStats",
        back_populates="profile",
        cascade="all, delete-orphan",
        uselist=False,
    )
    matches = db.relationship(
        "PlayerMatch",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    map_stats = db.relationship(
        "PlayerMapStats",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class PlayerSocialLink(db.Model):
    __tablename__ = "player_social_links"
    __table_args__ = (
        db.UniqueConstraint(
            "profile_id", "platform", name="uq_player_social_links_profile_platform"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform = db.Column(db.String(20), nullable=False)
    url = db.Column(db.String(500), nullable=False)

    profile = db.relationship("PlayerProfile", back_populates="social_links")


class PlayerCompetitiveProfile(db.Model):
    __tablename__ = "player_competitive_profiles"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    level = db.Column(db.Integer, nullable=True)
    elo = db.Column(db.Integer, nullable=True)
    xp = db.Column(db.Integer, nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="UNRANKED",
        server_default="UNRANKED",
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    profile = db.relationship("PlayerProfile", back_populates="competitive")


class PlayerStats(db.Model):
    __tablename__ = "player_stats"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    matches_played = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    wins = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    losses = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    draws = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    kills = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    deaths = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    assists = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    headshots = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    rounds_played = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    total_damage = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    profile = db.relationship("PlayerProfile", back_populates="stats")


class PlayerMatch(db.Model):
    __tablename__ = "player_matches"
    __table_args__ = (
        db.Index(
            "ix_player_matches_profile_played", "profile_id", "played_at"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    map_id = db.Column(
        db.Integer,
        db.ForeignKey("maps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    played_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    match_type = db.Column(
        db.String(20),
        nullable=False,
        default="COMPETITIVE",
        server_default="COMPETITIVE",
    )
    result = db.Column(db.String(10), nullable=False)
    kills = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    deaths = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    assists = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    headshots = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    rounds_played = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    damage = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    elo_before = db.Column(db.Integer, nullable=True)
    elo_after = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    profile = db.relationship("PlayerProfile", back_populates="matches")
    map = db.relationship("Map")


class PlayerMapStats(db.Model):
    __tablename__ = "player_map_stats"
    __table_args__ = (
        db.UniqueConstraint(
            "profile_id", "map_id", name="uq_player_map_stats_profile_map"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    map_id = db.Column(
        db.Integer,
        db.ForeignKey("maps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matches_played = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    wins = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    losses = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    draws = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    kills = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    deaths = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    assists = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    headshots = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    rounds_played = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    total_damage = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    profile = db.relationship("PlayerProfile", back_populates="map_stats")
    map = db.relationship("Map")
