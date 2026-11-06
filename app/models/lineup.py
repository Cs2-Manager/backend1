"""Lineups de granadas (lanzamientos de utilidad).

IMPORTANTE: este modelo representa lanzamientos de granadas, no las
alineaciones competitivas de cinco jugadores (`TeamLineup`).

Se amplía el modelo histórico `lineups` con un `scope` explícito:

- OFFICIAL: contenido del catálogo, gestionado por administradores.
- PERSONAL: contenido privado del creador. Nunca visible para otros usuarios
  ni para administradores globales.
- TEAM: copia compartida con un equipo, derivada de una propuesta aprobada.
  Editable por cualquier integrante actual.

La columna `visibility` se conserva por compatibilidad con el código anterior
y se mantiene sincronizada con `scope` (PUBLIC / PRIVATE / TEAM).
"""

from datetime import datetime, timezone

from app.extensions import db

GRENADE_TYPES = ("Smoke", "Molotov", "Flash", "HE", "Decoy", "Incendiary", "Flashbang", "HE Grenade")
SIDES = ("TR", "CT", "T")

LINEUP_SCOPES = ("OFFICIAL", "PERSONAL", "TEAM")
LINEUP_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED")
LINEUP_DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
LINEUP_SIDES = ("T", "CT", "BOTH")
LINEUP_GRENADE_TYPES = ("SMOKE", "FLASH", "MOLOTOV", "INCENDIARY", "HE", "DECOY")
THROW_TYPES = (
    "STANDING",
    "RUNNING",
    "WALKING",
    "JUMP_THROW",
    "RUNNING_JUMP_THROW",
    "CUSTOM",
)


def _utcnow():
    return datetime.now(timezone.utc)


class Lineup(db.Model):
    __tablename__ = "lineups"

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False, index=True)
    side = db.Column(db.String(4), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    video_url = db.Column(db.String(500), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    visibility = db.Column(db.String(10), nullable=False, default="PUBLIC", server_default="PUBLIC")
    difficulty = db.Column(db.String(10), nullable=False, default="MEDIUM", server_default="MEDIUM")
    status = db.Column(db.String(12), nullable=False, default="PUBLISHED", server_default="PUBLISHED")
    launch_zone = db.Column(db.String(120), nullable=False, default="", server_default="")
    impact_zone = db.Column(db.String(120), nullable=False, default="", server_default="")
    image_url = db.Column(db.String(500), nullable=True)
    position = db.Column(db.JSON, nullable=True)

    # Campos de la biblioteca avanzada de lineups.
    scope = db.Column(
        db.String(12),
        nullable=False,
        default="PERSONAL",
        server_default="PERSONAL",
        index=True,
    )
    launch_position = db.Column(db.JSON, nullable=True)
    impact_position = db.Column(db.JSON, nullable=True)
    launch_callout_id = db.Column(
        db.Integer, db.ForeignKey("callouts.id", ondelete="SET NULL"), nullable=True
    )
    impact_callout_id = db.Column(
        db.Integer, db.ForeignKey("callouts.id", ondelete="SET NULL"), nullable=True
    )
    throw_type = db.Column(db.String(30), nullable=False, default="", server_default="")
    instructions = db.Column(db.Text, nullable=False, default="", server_default="")
    notes = db.Column(db.Text, nullable=False, default="", server_default="")
    tags = db.Column(db.JSON, nullable=True)
    game_version = db.Column(db.String(40), nullable=False, default="", server_default="")
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    # Procedencia: se guardan como enteros sin FK para evitar ciclos entre
    # `lineups` y `team_grenade_lineup_proposals`. La propuesta sí referencia
    # la lineup mediante FK.
    source_lineup_id = db.Column(db.Integer, nullable=True, index=True)
    source_proposal_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    map = db.relationship("Map", backref="lineups")
    author = db.relationship("User", foreign_keys=[author_id])
    team = db.relationship("Team", foreign_keys=[team_id])
    media = db.relationship(
        "GrenadeLineupMedia",
        back_populates="lineup",
        cascade="all, delete-orphan",
        order_by="GrenadeLineupMedia.position",
    )
    revisions = db.relationship(
        "GrenadeLineupRevision",
        back_populates="lineup",
        cascade="all, delete-orphan",
        order_by="GrenadeLineupRevision.version.desc()",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "map_id": self.map_id,
            "type": self.type,
            "side": self.side,
            "title": self.title,
            "description": self.description,
            "video_url": self.video_url,
            "scope": self.scope,
            "status": self.status,
            "version": self.version,
        }


class GrenadeFavorite(db.Model):
    __tablename__ = 'grenade_favorites'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    lineup_id = db.Column(db.Integer, db.ForeignKey('lineups.id', ondelete='CASCADE'), primary_key=True)
