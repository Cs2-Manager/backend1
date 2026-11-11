"""Pruebas de integración Flask → servicio realtime.

Levantan un receptor HTTP local que valida la firma HMAC y registra los eventos
publicados por los servicios de equipos y propuestas. También cubren el endpoint
interno de identidad que NestJS puede consultar al aceptar un socket.
"""

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.extensions import db
from app.models import Map, Team, TeamMember, User
from app.realtime.signature import sign, verify
from app.security import generate_token, hash_password

SECRET = "integration-realtime-hmac-secret-32chars"


class _Receiver:
    """Contenedor mutable de peticiones recibidas."""

    def __init__(self):
        self.received = []

    def of_type(self, event_type):
        return [
            item
            for item in self.received
            if json.loads(item["body"].decode("utf-8"))["event_type"]
            == event_type
        ]


@pytest.fixture()
def receiver():
    received = _Receiver()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - API de BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.received.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"accepted":true}')

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    received.port = server.server_address[1]
    try:
        yield received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _enable(app, receiver):
    app.config.update(
        REALTIME_ENABLED=True,
        REALTIME_URL=f"http://127.0.0.1:{receiver.port}",
        REALTIME_HMAC_SECRET=SECRET,
        REALTIME_TIMEOUT_SECONDS=2,
    )


def _user(username, *, admin=False):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
        is_admin=admin,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


@pytest.fixture()
def scenario(app):
    captain = _user("rt-captain")
    coach = _user("rt-coach")
    author = _user("rt-author")
    outsider = _user("rt-outsider")
    admin = _user("rt-admin", admin=True)
    invitee = _user("rt-invitee")
    invitee2 = _user("rt-invitee2")

    team = Team(name="Realtime Team", tag="RTT", visibility="PRIVATE")
    other = Team(name="Other Team", tag="OTH", visibility="PRIVATE")
    map_obj = Map(name="Inferno", image_url="https://example.com/radar.png")
    db.session.add_all([team, other, map_obj])
    db.session.flush()

    db.session.add_all(
        [
            TeamMember(team_id=team.id, user_id=captain.id, role="CAPTAIN"),
            TeamMember(team_id=team.id, user_id=coach.id, role="COACH"),
            TeamMember(team_id=team.id, user_id=author.id, role="PLAYER"),
            TeamMember(team_id=other.id, user_id=outsider.id, role="CAPTAIN"),
        ]
    )
    db.session.commit()

    return {
        "captain": _headers(captain),
        "coach": _headers(coach),
        "author": _headers(author),
        "outsider": _headers(outsider),
        "admin": _headers(admin),
        "invitee": _headers(invitee),
        "invitee2": _headers(invitee2),
        "captain_id": captain.id,
        "coach_id": coach.id,
        "author_id": author.id,
        "outsider_id": outsider.id,
        "admin_id": admin.id,
        "invitee_id": invitee.id,
        "invitee2_id": invitee2.id,
        "team_id": team.id,
        "other_team_id": other.id,
        "map_id": map_obj.id,
    }


def _invite(client, scenario, headers, user_id):
    return client.post(
        f"/api/teams/{scenario['team_id']}/invitations",
        json={"user_id": user_id, "role": "PLAYER"},
        headers=headers,
    )


def _create_personal(client, scenario, headers, title="Smoke A"):
    response = client.post(
        f"/api/maps/{scenario['map_id']}/lineups",
        json={
            "map_id": scenario["map_id"],
            "type": "Smoke",
            "side": "T",
            "title": title,
            "description": "Desde T",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["lineup"]


def _assert_signed(item):
    headers = item["headers"]
    assert verify(
        SECRET,
        headers["X-Realtime-Timestamp"],
        headers["X-Realtime-Nonce"],
        item["body"],
        headers["X-Realtime-Signature"],
    )


def _event(item):
    return json.loads(item["body"].decode("utf-8"))


def test_invitation_created_notifies_only_the_invited_user(
    app, client, scenario, receiver
):
    _enable(app, receiver)

    response = _invite(client, scenario, scenario["captain"], scenario["invitee_id"])
    assert response.status_code == 201, response.get_json()

    events = receiver.of_type("team.invitation.created")
    assert len(events) == 1
    _assert_signed(events[0])
    event = _event(events[0])
    assert event["recipients"] == [scenario["invitee_id"]]
    assert event["team_id"] == scenario["team_id"]
    assert event["payload"]["team"]["name"] == "Realtime Team"
    assert event["payload"]["invited_by"]["user_id"] == scenario["captain_id"]
    # Ningún otro integrante ni el administrador global recibe la invitación.
    assert scenario["admin_id"] not in event["recipients"]
    assert scenario["author_id"] not in event["recipients"]


def test_invitation_accepted_notifies_current_managers(
    app, client, scenario, receiver
):
    _enable(app, receiver)
    created = _invite(
        client, scenario, scenario["captain"], scenario["invitee_id"]
    ).get_json()["invitation"]

    response = client.post(
        f"/api/teams/invitations/{created['id']}/accept",
        headers=scenario["invitee"],
    )
    assert response.status_code == 200, response.get_json()

    events = receiver.of_type("team.invitation.accepted")
    assert len(events) == 1
    _assert_signed(events[0])
    event = _event(events[0])
    assert set(event["recipients"]) == {
        scenario["captain_id"],
        scenario["coach_id"],
    }
    assert event["actor"]["user_id"] == scenario["invitee_id"]
    assert event["payload"]["member"]["user_id"] == scenario["invitee_id"]


def test_invitation_rejected_notifies_managers_and_inviter(
    app, client, scenario, receiver
):
    _enable(app, receiver)
    created = _invite(
        client, scenario, scenario["coach"], scenario["invitee2_id"]
    ).get_json()["invitation"]

    response = client.post(
        f"/api/teams/invitations/{created['id']}/reject",
        headers=scenario["invitee2"],
    )
    assert response.status_code == 200, response.get_json()

    events = receiver.of_type("team.invitation.rejected")
    assert len(events) == 1
    event = _event(events[0])
    assert set(event["recipients"]) == {
        scenario["captain_id"],
        scenario["coach_id"],
    }
    assert scenario["outsider_id"] not in event["recipients"]
    assert scenario["admin_id"] not in event["recipients"]


def test_proposal_lifecycle_events_and_privacy(app, client, scenario, receiver):
    _enable(app, receiver)

    lineup = _create_personal(client, scenario, scenario["author"])
    proposed = client.post(
        f"/api/grenade-lineups/{lineup['id']}/propose",
        json={"note": "Para el equipo"},
        headers=scenario["author"],
    )
    assert proposed.status_code == 201, proposed.get_json()
    proposal = proposed.get_json()["proposal"]

    created = receiver.of_type("grenade.proposal.created")
    assert len(created) == 1
    _assert_signed(created[0])
    event = _event(created[0])
    # Solo capitanes/entrenadores actuales; nunca el autor, otro equipo ni admin.
    assert set(event["recipients"]) == {
        scenario["captain_id"],
        scenario["coach_id"],
    }
    assert scenario["outsider_id"] not in event["recipients"]
    assert scenario["admin_id"] not in event["recipients"]
    assert event["payload"]["lineup"]["title"] == "Smoke A"
    assert event["payload"]["map"]["name"] == "Inferno"

    approved = client.post(
        f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
        headers=scenario["captain"],
    )
    assert approved.status_code == 200, approved.get_json()
    approved_lineup = approved.get_json()["lineup"]
    events = receiver.of_type("grenade.proposal.approved")
    assert len(events) == 1
    event = _event(events[0])
    assert event["recipients"] == [scenario["author_id"]]
    assert event["payload"]["approved_lineup_id"] == approved_lineup["id"]

    second = _create_personal(
        client, scenario, scenario["author"], title="Flash B"
    )
    proposal2 = client.post(
        f"/api/grenade-lineups/{second['id']}/propose",
        json={},
        headers=scenario["author"],
    ).get_json()["proposal"]
    rejected = client.post(
        f"/api/grenade-lineups/proposals/{proposal2['id']}/reject",
        json={"reason": "No aplica"},
        headers=scenario["coach"],
    )
    assert rejected.status_code == 200, rejected.get_json()

    rejected_events = receiver.of_type("grenade.proposal.rejected")
    assert len(rejected_events) == 1
    event = _event(rejected_events[0])
    assert event["recipients"] == [scenario["author_id"]]
    assert "reason" not in event["payload"]


def test_realtime_down_does_not_break_operations_and_recovers(
    app, client, scenario, receiver
):
    app.config.update(
        REALTIME_ENABLED=True,
        REALTIME_URL="http://127.0.0.1:1",
        REALTIME_HMAC_SECRET=SECRET,
        REALTIME_TIMEOUT_SECONDS=0.5,
    )
    failed = _invite(
        client, scenario, scenario["captain"], scenario["invitee_id"]
    )
    assert failed.status_code == 201, failed.get_json()
    assert receiver.received == []

    # Recuperación: el servicio vuelve a estar disponible y los eventos fluyen.
    _enable(app, receiver)
    recovered = _invite(
        client, scenario, scenario["captain"], scenario["invitee2_id"]
    )
    assert recovered.status_code == 201, recovered.get_json()
    assert len(receiver.of_type("team.invitation.created")) == 1


def _signed_identity(user_id, *, secret=SECRET, timestamp=None, nonce=None):
    body = json.dumps({"user_id": user_id}).encode("utf-8")
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    return body, {
        "Content-Type": "application/json",
        "X-Realtime-Timestamp": timestamp,
        "X-Realtime-Nonce": nonce,
        "X-Realtime-Signature": sign(secret, timestamp, nonce, body),
    }


def test_identity_endpoint_validates_hmac_replay_and_users(
    app, client, scenario
):
    app.config["REALTIME_HMAC_SECRET"] = SECRET
    body, headers = _signed_identity(scenario["author_id"])
    response = client.post(
        "/internal/realtime/identity", data=body, headers=headers
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "user_id": scenario["author_id"],
        "username": "rt-author",
        "active": True,
        "team_id": scenario["team_id"],
        "role": "PLAYER",
    }

    # Replay del mismo nonce.
    replay = client.post(
        "/internal/realtime/identity", data=body, headers=headers
    )
    assert replay.status_code == 401

    body, headers = _signed_identity(scenario["author_id"], secret="wrong-secret")
    assert (
        client.post(
            "/internal/realtime/identity", data=body, headers=headers
        ).status_code
        == 401
    )

    body, headers = _signed_identity(
        scenario["author_id"], timestamp=str(int(time.time()) - 3600)
    )
    assert (
        client.post(
            "/internal/realtime/identity", data=body, headers=headers
        ).status_code
        == 401
    )

    body, headers = _signed_identity(999999)
    assert (
        client.post(
            "/internal/realtime/identity", data=body, headers=headers
        ).status_code
        == 404
    )


def test_identity_endpoint_requires_configured_secret(app, client, scenario):
    app.config["REALTIME_HMAC_SECRET"] = ""
    body, headers = _signed_identity(scenario["author_id"])
    response = client.post(
        "/internal/realtime/identity", data=body, headers=headers
    )
    assert response.status_code == 503
