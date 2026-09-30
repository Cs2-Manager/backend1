from app.extensions import db

WORKSHOP_CATEGORIES = ("Aim", "Recoil", "Crosshair", "HUD", "Warmup")


class WorkshopMap(db.Model):
    __tablename__ = "workshop_maps"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    image_url = db.Column(db.String(500), nullable=False)
    workshop_url = db.Column(db.String(500), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "image_url": self.image_url,
            "workshop_url": self.workshop_url,
        }
