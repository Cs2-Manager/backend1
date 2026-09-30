from app.extensions import db


class Map(db.Model):
    __tablename__ = "maps"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    active_pool = db.Column(db.Boolean, nullable=False, default=False)

    callouts = db.relationship(
        "Callout",
        back_populates="map",
        cascade="all, delete-orphan",
        order_by="Callout.zone_name",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "image_url": self.image_url,
            "active_pool": self.active_pool,
            "callouts": [c.to_dict() for c in self.callouts],
        }


class Callout(db.Model):
    __tablename__ = "callouts"

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False, index=True)
    zone_name = db.Column(db.String(120), nullable=False)
    x_ratio = db.Column(db.Float, nullable=False)
    y_ratio = db.Column(db.Float, nullable=False)

    map = db.relationship("Map", back_populates="callouts")

    def to_dict(self):
        return {
            "id": self.id,
            "map_id": self.map_id,
            "zone_name": self.zone_name,
            "x_ratio": self.x_ratio,
            "y_ratio": self.y_ratio,
        }
