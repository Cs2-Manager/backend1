"""Isolated browser fixture server; never connects to the application database.

Run from back/: python -m scripts.phase8_browser_fixture <output-json>
Requires a pre-created PostgreSQL database named phase8_browser on localhost.
"""
import json
import sys
import uuid
from pathlib import Path
from sqlalchemy.engine import make_url
from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, Map, Team, TeamMember, TeamLineup, TeamLineupPlayer
from app.security import generate_token


class BrowserConfig(Config):
    SQLALCHEMY_DATABASE_URI = make_url(Config.SQLALCHEMY_DATABASE_URI).set(host='127.0.0.1', port=5432, database='phase8_browser').render_as_string(hide_password=False)
    TESTING = True


def main():
    app = create_app(BrowserConfig)
    assert make_url(app.config['SQLALCHEMY_DATABASE_URI']).database == 'phase8_browser'
    with app.app_context():
        db.create_all()
        suffix = uuid.uuid4().hex[:8]
        users = [User(username=f'phase8-{suffix}-{i}', email=f'{suffix}-{i}@example.com', password_hash='fixture', is_admin=i == 0) for i in range(5)]
        db.session.add_all(users); db.session.flush()
        team = Team(name=f'Browser team {suffix}', visibility='PRIVATE')
        map_obj = Map(name=f'Test map {suffix}', image_url='/phase8-radar.svg', description='Isolated browser validation fixture')
        db.session.add_all([team, map_obj]); db.session.flush()
        lineup = TeamLineup(team_id=team.id, map_id=map_obj.id, name='Browser Main', status='ACTIVE')
        db.session.add(lineup); db.session.flush()
        for i, user in enumerate(users):
            db.session.add(TeamMember(team_id=team.id, user_id=user.id, role='CAPTAIN' if i == 0 else 'PLAYER'))
            db.session.add(TeamLineupPlayer(lineup_id=lineup.id, user_id=user.id, is_starter=True, role='IGL' if i == 0 else 'RIFLER'))
        db.session.commit()
        Path(sys.argv[1]).write_text(json.dumps({'token': generate_token(users[0]), 'player_token': generate_token(users[1]), 'map_id': map_obj.id, 'team_id': team.id, 'lineup_id': lineup.id}), encoding='utf8')
    app.run(host='127.0.0.1', port=5001, use_reloader=False)


if __name__ == '__main__':
    main()
