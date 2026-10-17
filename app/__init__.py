from flask import Flask
from flask_cors import CORS

from app.config import Config
from app.errors import register_error_handlers
from app.extensions import db
from app.routes.auth import auth_bp
from app.routes.health import health_bp
from app.routes.lineups import lineups_bp
from app.routes.maps import maps_bp
from app.routes.workshop_maps import workshop_maps_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    # CORS configurable desde Config (por defecto localhost del frontend).
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=app.config["CORS_SUPPORTS_CREDENTIALS"],
    )

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp)
    app.register_blueprint(maps_bp)
    app.register_blueprint(lineups_bp)
    app.register_blueprint(workshop_maps_bp)

    register_error_handlers(app)

    with app.app_context():
        from app import models  # noqa: F401

    return app
