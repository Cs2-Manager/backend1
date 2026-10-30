"""Equipos competitivos, integrantes e invitaciones.

Reglas estructurales que se garantizan también en la base de datos:

- `team_members.user_id` es único: un usuario solo puede pertenecer a un equipo
  activo a la vez.
- Solo puede existir un capitán por equipo (índice único parcial).
- Solo puede existir una invitación `PENDING` por equipo/usuario (índice único
  parcial), permitiendo reinvitar después de un rechazo o cancelación.
"""

from datetime import datetime, timezone

from app.extensions import db

TEAM_VISIBILITIES = ("PUBLIC", "PRIVATE")
TEAM_ROLES = ("CAPTAIN", "COACH", "PLAYER")
INVITATION_STATUSES = ("PENDING", "ACCEPTED", "REJECTED", "CANCELLED")


def _utcnow():
    return datetime.now(timezone.utc)


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, index=True)
    tag = db.Column(db.String(10), nullable=True, unique=True, index=True)
    logo_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    country = db.Column(db.String(2), nullable=True)
    visibility = db.Column(
        db.String(10),
        nullable=False,
        default="PRIVATE",
        server_default="PRIVATE",
        index=True,
    )
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    created_by = db.relationship("User", foreign_keys=[created_by_id])
    members = db.relationship(
        "TeamMember",
        back_populates="team",
        cascade="all, delete-orphan",
        order_by="TeamMember.joined_at",
    )
    invitations = db.relationship(
        "TeamInvitation",
        back_populates="team",
        cascade="all, delete-orphan",
        order_by="TeamInvitation.created_at",
    )
    lineups = db.relationship(
        "TeamLineup",
        back_populates="team",
        cascade="all, delete-orphan",
        order_by="TeamLineup.created_at",
    )


class TeamMember(db.Model):
    __tablename__ = "team_members"
    __table_args__ = (
        # Un capitán como máximo por equipo. El servicio mantiene la regla
        # durante las transferencias, pero el índice evita estados inválidos.
        db.Index(
            "uq_team_members_one_captain",
            "team_id",
            unique=True,
            postgresql_where=db.text("role = 'CAPTAIN'"),
            sqlite_where=db.text("role = 'CAPTAIN'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    role = db.Column(
        db.String(10),
        nullable=False,
        default="PLAYER",
        server_default="PLAYER",
    )
    joined_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    team = db.relationship("Team", back_populates="members")
    user = db.relationship("User")


class TeamInvitation(db.Model):
    __tablename__ = "team_invitations"
    __table_args__ = (
        # Evita invitaciones pendientes duplicadas sin impedir el historial de
        # invitaciones rechazadas, canceladas o aceptadas.
        db.Index(
            "uq_team_invitations_pending",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=db.text("status = 'PENDING'"),
            sqlite_where=db.text("status = 'PENDING'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role = db.Column(
        db.String(10),
        nullable=False,
        default="PLAYER",
        server_default="PLAYER",
    )
    status = db.Column(
        db.String(10),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)

    team = db.relationship("Team", back_populates="invitations")
    user = db.relationship("User", foreign_keys=[user_id])
    invited_by = db.relationship("User", foreign_keys=[invited_by_id])
