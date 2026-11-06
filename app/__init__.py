from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from app.cli import register_cli
from app.config import Config
from app.errors import register_error_handlers
from app.extensions import db
from app.routes.auth import auth_bp
from app.routes.dashboard import dashboard_bp
from app.routes.faceit import faceit_bp
from app.routes.grenade_lineups import grenade_lineups_bp
from app.routes.health import health_bp
from app.routes.lineups import lineups_bp
from app.routes.maps import maps_bp
from app.routes.tactics import tactics_bp
from app.routes.matchmaking import matchmaking_bp
from app.routes.profiles import profiles_bp
from app.routes.steam import steam_bp
from app.routes.team_lineups import team_lineups_bp
from app.routes.teams import teams_bp
from app.routes.workshop_maps import workshop_maps_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Detrás del proxy inverso hay exactamente 1 salto confiable (nginx en
    # Docker Compose), que normaliza X-Forwarded-For y X-Forwarded-Proto.
    # ProxyFix restituye la IP y el esquema reales del cliente a partir del
    # último valor de cada header. Sin proxy (desarrollo local) esos headers
    # no existen y esto es un no-op.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)

    # CORS configurable desde Config (por defecto localhost del frontend).
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=app.config["CORS_SUPPORTS_CREDENTIALS"],
    )

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(maps_bp)
    app.register_blueprint(tactics_bp)
    app.register_blueprint(lineups_bp)
    app.register_blueprint(grenade_lineups_bp)
    app.register_blueprint(profiles_bp)
    app.register_blueprint(matchmaking_bp)
    app.register_blueprint(faceit_bp)
    app.register_blueprint(steam_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(team_lineups_bp)
    app.register_blueprint(workshop_maps_bp)

    register_error_handlers(app)
    register_cli(app)

    with app.app_context():
        from app import models  # noqa: F401

    return app
