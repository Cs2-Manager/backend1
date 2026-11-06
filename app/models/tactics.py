"""Team-owned tactical documents with immutable revisions."""
from datetime import datetime, timezone
from app.extensions import db


def now():
    return datetime.now(timezone.utc)


class TeamStrategy(db.Model):
    __tablename__ = "team_strategies"
    __table_args__ = (db.CheckConstraint("status IN ('DRAFT','PUBLISHED','ARCHIVED')", name="ck_strategy_status"),)
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id", ondelete="RESTRICT"), nullable=False, index=True)
    lineup_id = db.Column(db.Integer, db.ForeignKey("team_lineups.id", ondelete="SET NULL"))
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    side = db.Column(db.String(2), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(12), nullable=False, default="DRAFT")
    version = db.Column(db.Integer, nullable=False, default=1)
    document = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": version}


class StrategyRevision(db.Model):
    __tablename__ = "strategy_revisions"
    __table_args__ = (db.UniqueConstraint("strategy_id", "version", name="uq_strategy_revision"),)
    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey("team_strategies.id", ondelete="CASCADE"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)


class TeamMapSetup(db.Model):
    __tablename__ = "team_map_setups"
    __table_args__ = (db.UniqueConstraint("team_id", "map_id", name="uq_team_map_setup"),)
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id", ondelete="CASCADE"), nullable=False)
    lineup_id = db.Column(db.Integer, db.ForeignKey("team_lineups.id", ondelete="SET NULL"))
    notes = db.Column(db.Text, nullable=False, default="")
    readiness = db.Column(db.String(20), nullable=False, default="NOT_STARTED")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}
