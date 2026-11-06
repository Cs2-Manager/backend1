"""Isolated FACEIT browser fixture; never connects to the application database.

Run from back/: python -m scripts.faceit_browser_fixture <output-json>
Requires a pre-created PostgreSQL database named faceit_browser on localhost.
The script only writes fixture rows and serves the real Flask API on port 5001,
so the deployed frontend can render the actual serializers without touching
production data or calling the real FACEIT API.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User
from app.models.faceit import (
    FaceitAccount,
    FaceitEloSnapshot,
    FaceitMapStats,
    FaceitMatch,
    FaceitMatchPlayerStats,
    FaceitPlayerStats,
    FaceitSyncState,
)
from app.models.steam import SteamAccount
from app.security import generate_token

PLAYER_ID = "faceit-browser-player"
STEAM_ID = "76561198000000001"


class BrowserConfig(Config):
    SQLALCHEMY_DATABASE_URI = make_url(Config.SQLALCHEMY_DATABASE_URI).set(
        host="127.0.0.1", port=5432, database="faceit_browser"
    ).render_as_string(hide_password=False)
    TESTING = True
    # Configuración ficticia: la UI se ejercita sin llamar a FACEIT.
    FACEIT_ENABLED = True
    FACEIT_API_KEY = "fixture-api-key"
    FACEIT_OAUTH_CLIENT_ID = "fixture-client"
    FACEIT_OAUTH_CLIENT_SECRET = "fixture-secret"
    FACEIT_OAUTH_REDIRECT_URI = (
        "http://localhost/api/faceit/oauth/callback"
    )
    FACEIT_SYNC_MIN_INTERVAL_SECONDS = 0


def main():
    app = create_app(BrowserConfig)
    assert make_url(app.config["SQLALCHEMY_DATABASE_URI"]).database == (
        "faceit_browser"
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f"faceit-{suffix}",
            email=f"faceit-{suffix}@example.com",
            password_hash="fixture",
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            SteamAccount(
                user_id=user.id,
                steam_id=STEAM_ID,
                persona_name="SteamUser",
                last_sync_status="OK",
            )
        )

        account = FaceitAccount(
            user_id=user.id,
            faceit_player_id=PLAYER_ID,
            nickname="FaceitUser",
            country="ar",
            region="SA",
            steam_id=STEAM_ID,
            steam_nickname="SteamUser",
            faceit_url=f"https://www.faceit.com/en/players/{PLAYER_ID}",
            elo=2100,
            skill_level=9,
            link_status="VERIFIED",
            verification_source="OAUTH2",
            verified_at=datetime(2026, 10, 1, 9, 0, 0),
        )
        db.session.add(account)
        db.session.flush()

        db.session.add(
            FaceitPlayerStats(
                account_id=account.id,
                matches_played=120,
                wins=70,
                losses=50,
                win_rate=58.3,
                kills=2400,
                deaths=1800,
                assists=500,
                kd=1.33,
                kr=0.79,
                headshots=1100,
                headshot_percentage=45.8,
                adr=82.4,
                mvps=220,
                triple_kills=30,
                quadruple_kills=4,
                penta_kills=1,
                rounds_played=2700,
                total_damage=220000,
                fetched_at=datetime(2026, 10, 1, 10, 0, 0),
            )
        )

        matches = [
            {
                "faceit_match_id": "1-abc",
                "map_name": "de_mirage",
                "result": "WIN",
                "team_score": 13,
                "opponent_score": 7,
                "score": "13 / 7",
                "played_at": datetime(2026, 10, 1, 10, 0, 0),
                "stats": {
                    "kills": 22,
                    "deaths": 14,
                    "assists": 4,
                    "kd": 1.57,
                    "kr": 0.88,
                    "adr": 91.2,
                    "headshot_percentage": 52,
                    "mvps": 4,
                    "rounds_played": 20,
                },
            },
            {
                "faceit_match_id": "1-def",
                "map_name": "de_ancient",
                "result": "LOSS",
                "team_score": 9,
                "opponent_score": 13,
                "score": "9 / 13",
                "played_at": datetime(2026, 9, 30, 18, 0, 0),
                "stats": {
                    "kills": 12,
                    "deaths": 18,
                    "assists": 3,
                    "kd": 0.67,
                    "kr": 0.55,
                    "adr": 64.5,
                    "headshot_percentage": 38,
                    "mvps": 1,
                    "rounds_played": 22,
                },
            },
        ]
        for item in matches:
            match = FaceitMatch(
                account_id=account.id,
                faceit_match_id=item["faceit_match_id"],
                played_at=item["played_at"],
                game_mode="5v5",
                map_name=item["map_name"],
                region="SA",
                competition_name="Ranked",
                result=item["result"],
                team_score=item["team_score"],
                opponent_score=item["opponent_score"],
                score=item["score"],
                player_team_name="Our Team",
                opponent_team_name="Enemy Team",
                faceit_url=(
                    "https://www.faceit.com/en/cs2/room/"
                    + item["faceit_match_id"]
                ),
                status="OK",
                fetched_at=datetime(2026, 10, 1, 10, 0, 0),
            )
            db.session.add(match)
            db.session.flush()
            db.session.add(
                FaceitMatchPlayerStats(
                    match_id=match.id,
                    fetched_at=datetime(2026, 10, 1, 10, 0, 0),
                    **item["stats"],
                )
            )

        for row in (
            {
                "map_name": "de_mirage",
                "matches_played": 40,
                "wins": 25,
                "losses": 15,
                "win_rate": 62.5,
                "kills": 820,
                "deaths": 600,
                "assists": 170,
                "kd": 1.37,
                "adr": 85.1,
                "headshot_percentage": 48,
            },
            {
                "map_name": "de_ancient",
                "matches_played": 22,
                "wins": 10,
                "losses": 12,
                "win_rate": 45.5,
                "kills": 410,
                "deaths": 402,
                "assists": 95,
                "kd": 1.02,
                "adr": 74.3,
                "headshot_percentage": 41,
            },
        ):
            db.session.add(FaceitMapStats(account_id=account.id, **row))

        for elo, captured_at in (
            (2050, datetime(2026, 9, 20, 10, 0, 0)),
            (2080, datetime(2026, 9, 25, 10, 0, 0)),
            (2100, datetime(2026, 10, 1, 10, 0, 0)),
        ):
            db.session.add(
                FaceitEloSnapshot(
                    account_id=account.id,
                    elo=elo,
                    skill_level=9,
                    captured_at=captured_at,
                )
            )

        db.session.add(
            FaceitSyncState(
                account_id=account.id,
                status="OK",
                last_attempt_at=datetime(2026, 10, 1, 10, 0, 0),
                last_success_at=datetime(2026, 10, 1, 10, 0, 0),
                next_sync_at=None,
            )
        )
        db.session.commit()

        Path(sys.argv[1]).write_text(
            json.dumps(
                {
                    "token": generate_token(user),
                    "player_id": PLAYER_ID,
                    "user_id": user.id,
                }
            ),
            encoding="utf8",
        )
    app.run(host="127.0.0.1", port=5001, use_reloader=False)


if __name__ == "__main__":
    main()
