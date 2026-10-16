from app.extensions import db

GRENADE_TYPES = ("Smoke", "Molotov", "Flash", "HE", "Decoy")
SIDES = ("TR", "CT")


class Lineup(db.Model):
    __tablename__ = "lineups"

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False, index=True)
    side = db.Column(db.String(4), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    video_url = db.Column(db.String(500), nullable=False)

    map = db.relationship("Map", backref="lineups")

    def to_dict(self):
        return {
            "id": self.id,
            "map_id": self.map_id,
            "type": self.type,
            "side": self.side,
            "title": self.title,
            "description": self.description,
            "video_url": self.video_url,
        }
