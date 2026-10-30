"""Alineaciones competitivas de un equipo.

Una lineup pertenece a un equipo y agrupa jugadores titulares y suplentes con
un rol de juego independiente de los roles de permiso del equipo
(`CAPTAIN`, `COACH`, `PLAYER`).

Reglas estructurales garantizadas por la base de datos:

- Un jugador no puede repetirse dentro de la misma lineup
  (`team_lineup_players` es único por `lineup_id` + `user_id`).
- Solo puede existir una lineup principal por equipo (índice único parcial).
- El estado y los roles de juego se limitan a los valores canónicos.
"""

from datetime import datetime, timezone

from app.extensions import db

TEAM_LINEUP_STATUSES = ("DRAFT", "ACTIVE")
TEAM_LINEUP_ROLES = (
    "IGL",
    "AWPER",
    "ENTRY",
    "SUPPORT",
    "LURKER",
    "ANCHOR",
    "RIFLER",
    "FLEX",
)
TEAM_LINEUP_STARTERS = 5
TEAM_LINEUP_MAX_SUBSTITUTES = 5


def _utcnow():
    return datetime.now(timezone.utc)


class TeamLineup(db.Model):
    __tablename__ = "team_lineups"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE')",
            name="ck_team_lineups_status",
        ),
        # Una sola lineup principal por equipo. El servicio mantiene la regla
        # dentro de una transacción; el índice evita estados inválidos.
        db.Index(
            "uq_team_lineups_one_primary",
            "team_id",
            unique=True,
            postgresql_where=db.text("is_primary"),
            sqlite_where=db.text("is_primary"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.String(10),
        nullable=False,
        default="DRAFT",
        server_default="DRAFT",
        index=True,
    )
    is_primary = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    team = db.relationship("Team", back_populates="lineups")
    players = db.relationship(
        "TeamLineupPlayer",
        back_populates="lineup",
        cascade="all, delete-orphan",
        order_by="TeamLineupPlayer.id",
    )


class TeamLineupPlayer(db.Model):
    __tablename__ = "team_lineup_players"
    __table_args__ = (
        db.UniqueConstraint(
            "lineup_id",
            "user_id",
            name="uq_team_lineup_players_lineup_user",
        ),
        db.CheckConstraint(
            "role IS NULL OR role IN "
            "('IGL', 'AWPER', 'ENTRY', 'SUPPORT', 'LURKER', 'ANCHOR', "
            "'RIFLER', 'FLEX')",
            name="ck_team_lineup_players_role",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    lineup_id = db.Column(
        db.Integer,
        db.ForeignKey("team_lineups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(10), nullable=True)
    is_starter = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    lineup = db.relationship("TeamLineup", back_populates="players")
    user = db.relationship("User")
