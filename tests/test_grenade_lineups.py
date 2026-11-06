"""Pruebas de la biblioteca de lineups de granadas.

Cubren privacidad estricta, catálogo oficial, propuestas, aprobación por
capitán/entrenador, edición por cualquier integrante, versionado y disolución
de equipos.
"""

import pytest

from app.extensions import db
from app.models import Map, Team, TeamMember, User
from app.security import generate_token, hash_password

VALID_VIDEO = "https://youtu.be/dQw4w9WgXcQ"


@pytest.fixture()
def grenade(app):
    users = [
        User(
            username=f"grenade-{i}",
            email=f"grenade-{i}@example.com",
            password_hash=hash_password("secret123"),
            is_admin=i == 5,
        )
        for i in range(6)
    ]
    db.session.add_all(users)
    db.session.flush()

    team = Team(name="Grenade team", visibility="PRIVATE")
    other = Team(name="Other grenade team", visibility="PRIVATE")
    map_obj = Map(name="Mirage", image_url="https://example.com/radar.png")
    db.session.add_all([team, other, map_obj])
    db.session.flush()

    roles = ("CAPTAIN", "COACH", "PLAYER")
    for index, role in enumerate(roles):
        db.session.add(
            TeamMember(team_id=team.id, user_id=users[index].id, role=role)
        )
    db.session.add(
        TeamMember(team_id=other.id, user_id=users[4].id, role="CAPTAIN")
    )
    db.session.commit()

    headers = [
        {"Authorization": f"Bearer {generate_token(user)}"} for user in users
    ]
    return {
        "users": [user.id for user in users],
        "headers": headers,
        "captain": headers[0],
        "coach": headers[1],
        "player": headers[2],
        "outsider": headers[3],
        "admin": headers[5],
        "team": team.id,
        "other_team": other.id,
        "map": map_obj.id,
    }


def _payload(map_id, **overrides):
    data = {
        "map_id": map_id,
        "type": "Smoke",
        "side": "T",
        "title": "Smoke A",
        "description": "Desde T",
    }
    data.update(overrides)
    return data


def _create_personal(client, grenade, **overrides):
    response = client.post(
        f"/api/maps/{grenade['map']}/lineups",
        json=_payload(grenade["map"], **overrides),
        headers=grenade["captain"],
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["lineup"]


def test_personal_lineups_are_invisible_to_others_and_admins(client, grenade):
    lineup = _create_personal(client, grenade, title="Mi smoke privada")
    lineup_id = lineup["id"]

    assert lineup["scope"] == "PERSONAL"
    assert lineup["visibility"] == "PRIVATE"

    assert client.get(f"/api/grenade-lineups/{lineup_id}").status_code == 404
    assert (
        client.get(
            f"/api/grenade-lineups/{lineup_id}", headers=grenade["player"]
        ).status_code
        == 404
    )
    # Un administrador global tampoco accede al contenido personal ajeno.
    assert (
        client.get(
            f"/api/grenade-lineups/{lineup_id}", headers=grenade["admin"]
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/grenade-lineups/{lineup_id}",
            json={"title": "secuestrada"},
            headers=grenade["player"],
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/grenade-lineups/{lineup_id}", headers=grenade["admin"]
        ).status_code
        == 404
    )

    mine = client.get(
        "/api/grenade-lineups/personal", headers=grenade["captain"]
    ).get_json()["lineups"]
    assert [item["id"] for item in mine] == [lineup_id]

    others = client.get(
        "/api/grenade-lineups/personal", headers=grenade["player"]
    ).get_json()["lineups"]
    assert others == []

    # El listado por mapa tampoco filtra el contenido personal ajeno.
    listed = client.get(
        f"/api/maps/{grenade['map']}/lineups",
        query_string={"scope": "PERSONAL"},
        headers=grenade["player"],
    ).get_json()["lineups"]
    assert listed == []


def test_official_catalog_requires_admin_and_publish(client, grenade):
    denied = client.post(
        f"/api/maps/{grenade['map']}/lineups",
        json=_payload(grenade["map"]),
        query_string={"scope": "OFFICIAL"},
        headers=grenade["captain"],
    )
    assert denied.status_code == 403

    created = client.post(
        f"/api/maps/{grenade['map']}/lineups",
        json=_payload(grenade["map"], title="Oficial smoke"),
        query_string={"scope": "OFFICIAL"},
        headers=grenade["admin"],
    )
    assert created.status_code == 201, created.get_json()
    lineup = created.get_json()["lineup"]
    assert lineup["scope"] == "OFFICIAL"
    assert lineup["status"] == "DRAFT"

    public = client.get(
        f"/api/maps/{grenade['map']}/lineups",
        query_string={"scope": "OFFICIAL"},
    ).get_json()["lineups"]
    assert public == []

    admin_list = client.get(
        f"/api/maps/{grenade['map']}/lineups",
        query_string={"scope": "OFFICIAL", "status": "ALL"},
        headers=grenade["admin"],
    ).get_json()["lineups"]
    assert [item["id"] for item in admin_list] == [lineup["id"]]

    published = client.post(
        f"/api/grenade-lineups/{lineup['id']}/publish",
        headers=grenade["admin"],
    )
    assert published.status_code == 200
    assert published.get_json()["lineup"]["status"] == "PUBLISHED"

    public = client.get(
        f"/api/maps/{grenade['map']}/lineups",
        query_string={"scope": "OFFICIAL"},
    ).get_json()["lineups"]
    assert [item["id"] for item in public] == [lineup["id"]]

    assert (
        client.post(
            f"/api/grenade-lineups/{lineup['id']}/archive",
            headers=grenade["admin"],
        ).status_code
        == 200
    )
    public = client.get(
        f"/api/maps/{grenade['map']}/lineups",
        query_string={"scope": "OFFICIAL"},
    ).get_json()["lineups"]
    assert public == []


def test_proposal_approval_creates_team_lineup(client, grenade):
    personal = _create_personal(client, grenade, title="Propuesta smoke")
    personal_id = personal["id"]

    proposed = client.post(
        f"/api/grenade-lineups/{personal_id}/propose",
        json={"note": "Para el equipo"},
        headers=grenade["captain"],
    )
    assert proposed.status_code == 201, proposed.get_json()
    proposal = proposed.get_json()["proposal"]
    assert proposal["status"] == "PENDING"

    # Un integrante PLAYER no puede aprobar.
    assert (
        client.post(
            f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
            headers=grenade["player"],
        ).status_code
        == 403
    )
    # Un administrador global ajeno al equipo tampoco.
    assert (
        client.post(
            f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
            headers=grenade["admin"],
        ).status_code
        == 403
    )

    approved = client.post(
        f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
        headers=grenade["coach"],
    )
    assert approved.status_code == 200, approved.get_json()
    payload = approved.get_json()
    assert payload["proposal"]["status"] == "APPROVED"
    team_lineup = payload["lineup"]
    assert team_lineup["scope"] == "TEAM"
    assert team_lineup["team_id"] == grenade["team"]
    assert team_lineup["source_lineup_id"] == personal_id
    assert team_lineup["version"] == 1

    # La copia personal permanece privada para el equipo.
    assert (
        client.get(
            f"/api/grenade-lineups/{personal_id}", headers=grenade["player"]
        ).status_code
        == 404
    )

    # Cualquier integrante actual puede editar la copia de equipo.
    updated = client.put(
        f"/api/grenade-lineups/{team_lineup['id']}",
        json={"title": "Smoke editada por player", "version": 1},
        headers=grenade["player"],
    )
    assert updated.status_code == 200, updated.get_json()
    assert updated.get_json()["lineup"]["version"] == 2

    # Un usuario ajeno no puede verla ni editarla.
    assert (
        client.get(
            f"/api/grenade-lineups/{team_lineup['id']}",
            headers=grenade["outsider"],
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/grenade-lineups/{team_lineup['id']}",
            json={"title": "ajena", "version": 2},
            headers=grenade["outsider"],
        ).status_code
        == 404
    )

    # Control de concurrencia optimista.
    conflict = client.put(
        f"/api/grenade-lineups/{team_lineup['id']}",
        json={"title": "stale", "version": 1},
        headers=grenade["coach"],
    )
    assert conflict.status_code == 409


def test_team_lineup_history_and_restore(client, grenade):
    personal = _create_personal(client, grenade, title="Versionada")
    proposal = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    ).get_json()["proposal"]
    team_lineup = client.post(
        f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
        headers=grenade["captain"],
    ).get_json()["lineup"]

    client.put(
        f"/api/grenade-lineups/{team_lineup['id']}",
        json={"title": "Versión 2", "version": 1},
        headers=grenade["player"],
    )

    history = client.get(
        f"/api/grenade-lineups/{team_lineup['id']}/revisions",
        headers=grenade["player"],
    )
    assert history.status_code == 200
    revisions = history.get_json()["revisions"]
    assert [item["version"] for item in revisions] == [2, 1]
    assert revisions[0]["snapshot"]["title"] == "Versión 2"

    restored = client.post(
        f"/api/grenade-lineups/{team_lineup['id']}/revisions/1/restore",
        json={"version": 2},
        headers=grenade["coach"],
    )
    assert restored.status_code == 200, restored.get_json()
    lineup = restored.get_json()["lineup"]
    assert lineup["title"] == "Versionada"
    assert lineup["version"] == 3

    stale = client.post(
        f"/api/grenade-lineups/{team_lineup['id']}/revisions/1/restore",
        json={"version": 2},
        headers=grenade["coach"],
    )
    assert stale.status_code == 409


def test_proposal_reject_and_cancel(client, grenade):
    personal = _create_personal(client, grenade, title="Rechazable")
    proposal = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    ).get_json()["proposal"]

    rejected = client.post(
        f"/api/grenade-lineups/proposals/{proposal['id']}/reject",
        json={"reason": "No encaja"},
        headers=grenade["coach"],
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["proposal"]["status"] == "REJECTED"
    assert rejected.get_json()["proposal"]["rejection_reason"] == "No encaja"

    assert (
        client.post(
            f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
            headers=grenade["captain"],
        ).status_code
        == 409
    )

    second = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    ).get_json()["proposal"]
    assert (
        client.post(
            f"/api/grenade-lineups/proposals/{second['id']}/cancel",
            headers=grenade["player"],
        ).status_code
        == 403
    )
    cancelled = client.post(
        f"/api/grenade-lineups/proposals/{second['id']}/cancel",
        headers=grenade["captain"],
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["proposal"]["status"] == "CANCELLED"


def test_duplicate_pending_proposal_is_rejected(client, grenade):
    personal = _create_personal(client, grenade, title="Duplicada")
    first = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    )
    assert second.status_code == 409


def test_team_dissolution_archives_grenade_lineups(client, grenade):
    personal = _create_personal(client, grenade, title="Sobrevive")
    proposal = client.post(
        f"/api/grenade-lineups/{personal['id']}/propose",
        headers=grenade["captain"],
    ).get_json()["proposal"]
    team_lineup = client.post(
        f"/api/grenade-lineups/proposals/{proposal['id']}/approve",
        headers=grenade["captain"],
    ).get_json()["lineup"]

    # El capitán es el único integrante restante: se elimina el equipo.
    from app.models import TeamMember

    db.session.query(TeamMember).filter(
        TeamMember.team_id == grenade["team"],
        TeamMember.user_id != grenade["users"][0],
    ).delete(synchronize_session=False)
    db.session.commit()

    left = client.post(
        f"/api/teams/{grenade['team']}/leave", headers=grenade["captain"]
    )
    assert left.status_code in (200, 204), left.get_json()

    # El contenido de equipo quedó archivado y desvinculado.
    from app.models import Lineup

    archived = db.session.get(Lineup, team_lineup["id"])
    assert archived is not None
    assert archived.status == "ARCHIVED"
    assert archived.team_id is None
    assert archived.visibility == "PRIVATE"

    # La copia personal del autor sigue existiendo y siendo suya.
    assert (
        client.get(
            f"/api/grenade-lineups/{personal['id']}",
            headers=grenade["captain"],
        ).status_code
        == 200
    )


def test_legacy_endpoints_still_work(client, grenade):
    """La ruta histórica conserva su contrato y sus restricciones."""

    created = client.post(
        "/api/lineups",
        json={
            "map_id": grenade["map"],
            "type": "Smoke",
            "side": "CT",
            "title": "Legacy smoke",
            "video_url": VALID_VIDEO,
        },
        headers=grenade["admin"],
    )
    assert created.status_code == 201, created.get_json()
    lineup_id = created.get_json()["lineup"]["id"]

    assert client.get(f"/api/lineups/{lineup_id}").status_code == 200
    assert (
        client.post(
            "/api/lineups",
            json={
                "map_id": grenade["map"],
                "type": "Smoke",
                "side": "CT",
                "title": "No permitida",
                "video_url": VALID_VIDEO,
            },
            headers=grenade["player"],
        ).status_code
        == 403
    )
