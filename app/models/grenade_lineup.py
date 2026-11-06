"""Modelos de soporte para la biblioteca avanzada de lineups de granadas.

Se mantienen separados del modelo principal `Lineup` para no sobrecargarlo,
pero todos cuelgan de él: no existe un segundo sistema paralelo.
"""

from datetime import datetime, timezone

from app.extensions import db

PROPOSAL_STATUSES = ("PENDING", "APPROVED", "REJECTED", "CANCELLED")
MEDIA_KINDS = ("IMAGE", "VIDEO")


def _utcnow():
    return datetime.now(timezone.utc)


class GrenadeLineupMedia(db.Model):
    __tablename__ = "grenade_lineup_media"

    id = db.Column(db.Integer, primary_key=True)
    lineup_id = db.Column(
        db.Integer,
        db.ForeignKey("lineups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = db.Column(db.String(10), nullable=False, default="IMAGE", server_default="IMAGE")
    url = db.Column(db.String(500), nullable=False)
    thumbnail_url = db.Column(db.String(500), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    lineup = db.relationship("Lineup", back_populates="media")


class GrenadeLineupRevision(db.Model):
    """Snapshot inmutable de una lineup en una versión concreta."""

    __tablename__ = "grenade_lineup_revisions"
    __table_args__ = (
        db.UniqueConstraint(
            "lineup_id", "version", name="uq_grenade_lineup_revision"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    lineup_id = db.Column(
        db.Integer,
        db.ForeignKey("lineups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = db.Column(
        db.String(30), nullable=False, default="UPDATE", server_default="UPDATE"
    )
    snapshot = db.Column(db.JSON, nullable=False)
    change_summary = db.Column(db.Text, nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    lineup = db.relationship("Lineup", back_populates="revisions")
    actor = db.relationship("User", foreign_keys=[actor_id])


class TeamGrenadeLineupProposal(db.Model):
    """Propuesta de una lineup personal para compartirla con un equipo."""

    __tablename__ = "team_grenade_lineup_proposals"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELLED')",
            name="ck_team_grenade_proposal_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    map_id = db.Column(
        db.Integer,
        db.ForeignKey("maps.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_lineup_id = db.Column(
        db.Integer,
        db.ForeignKey("lineups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    author_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_lineup_id = db.Column(
        db.Integer,
        db.ForeignKey("lineups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    snapshot = db.Column(db.JSON, nullable=False)
    status = db.Column(
        db.String(12),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
        index=True,
    )
    note = db.Column(db.Text, nullable=False, default="", server_default="")
    rejection_reason = db.Column(db.Text, nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    source_lineup = db.relationship("Lineup", foreign_keys=[source_lineup_id])
    approved_lineup = db.relationship("Lineup", foreign_keys=[approved_lineup_id])
    author = db.relationship("User", foreign_keys=[author_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])
