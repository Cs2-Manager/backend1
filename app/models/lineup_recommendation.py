from app.extensions import db


class LineupRecommendation(db.Model):
    __tablename__ = 'lineup_recommendations'
    lineup_id = db.Column(db.Integer, db.ForeignKey('team_lineups.id', ondelete='CASCADE'), primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('team_strategies.id', ondelete='CASCADE'), primary_key=True)
