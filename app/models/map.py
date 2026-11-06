"""Catálogo de mapas y callouts.

`image_url` sigue siendo la representación top-down usada por el editor
táctico y por las coordenadas normalizadas de callouts y lineups. `cover_url`
es la imagen principal de la tarjeta. Los metadatos de biblioteca son
aditivos: los mapas existentes conservan sus imágenes y coordenadas.
"""

from datetime import datetime, timezone

from app.extensions import db

MAP_CATEGORIES = (
    "COMPETITIVE",
    "RESERVE",
    "TEMPORARY",
    "RETIRED",
    "ARCHIVED",
)
MAP_STATUSES = ("ACTIVE", "ARCHIVED")


def _utcnow():
    return datetime.now(timezone.utc)


class Map(db.Model):
    __tablename__ = "maps"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(80), unique=True, nullable=True, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    cover_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=False, default="", server_default="")
    active_pool = db.Column(db.Boolean, nullable=False, default=False)
    category = db.Column(
        db.String(20),
        nullable=False,
        default="COMPETITIVE",
        server_default="COMPETITIVE",
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
        index=True,
    )
    image_source = db.Column(db.String(300), nullable=True)
    top_down_source = db.Column(db.String(300), nullable=True)
    visual_version = db.Column(
        db.Integer, nullable=False, default=1, server_default="1"
    )
    display_order = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    release_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

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
            "slug": self.slug,
            "image_url": self.image_url,
            "cover_url": self.cover_url,
            "description": self.description,
            "active_pool": self.active_pool,
            "category": self.category,
            "status": self.status,
            "callouts": [c.to_dict() for c in self.callouts],
        }


class Callout(db.Model):
    __tablename__ = "callouts"

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False, index=True)
    zone_name = db.Column(db.String(120), nullable=False)
    x_ratio = db.Column(db.Float, nullable=False)
    y_ratio = db.Column(db.Float, nullable=False)
    zone = db.Column(db.String(120), nullable=False, default="", server_default="")
    description = db.Column(db.Text, nullable=False, default="", server_default="")
    image_url = db.Column(db.String(500))
    status = db.Column(db.String(12), nullable=False, default="PUBLISHED", server_default="PUBLISHED")
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))

    map = db.relationship("Map", back_populates="callouts")

    def to_dict(self):
        return {
            "id": self.id,
            "map_id": self.map_id,
            "zone_name": self.zone_name,
            "x_ratio": self.x_ratio,
            "y_ratio": self.y_ratio,
        }
