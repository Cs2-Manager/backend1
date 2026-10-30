"""Pruebas del sistema de alineaciones competitivas de equipos."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.team import Team, TeamMember
from app.models.team_lineup import (
    TEAM_LINEUP_ROLES,
    TeamLineup,
    TeamLineupPlayer,
)
from app.models.user import User
from app.security import generate_token, hash_password


def _create_user(username, *, is_admin=False):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _create_team(client, headers, *, name="Lineup Team", visibility="PUBLIC"):
    response = client.post(
        "/api/teams",
        json={"name": name, "visibility": visibility},
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["team"]


def _add_member(client, captain_headers, team_id, user, *, role="PLAYER"):
    response = client.post(
        f"/api/teams/{team_id}/invitations",
        json={"user_id": user.id, "role": role},
        headers=captain_headers,
    )
    assert response.status_code == 201, response.get_json()
    invitation_id = response.get_json()["invitation"]["id"]
    accepted = client.post(
        f"/api/teams/invitations/{invitation_id}/accept",
        headers=_headers(user),
    )
    assert accepted.status_code == 200, accepted.get_json()
    return accepted.get_json()


def _setup_team(client, *, total_members=5, visibility="PUBLIC"):
    """Crea un equipo con capitán y ``total_members - 1`` jugadores."""
    captain = _create_user("lineup-captain")
    headers = _headers(captain)
    team = _create_team(
        client, headers, name="Lineup Team", visibility=visibility
    )
    members = [captain]
    for index in range(1, total_members):
        member = _create_user(f"lineup-player-{index}")
        _add_member(client, headers, team["id"], member)
        members.append(member)
    return captain, headers, team, members


def _entries(users, roles=None):
    return [
        {
            "user_id": user.id,
            "role": roles[index] if roles else None,
        }
        for index, user in enumerate(users)
    ]


def _create_lineup(
    client,
    headers,
    team_id,
    *,
    name="Main Lineup",
    starters=None,
    substitutes=None,
    status=None,
    description=None,
):
    payload = {
        "name": name,
        "starters": _entries(starters or []),
        "substitutes": _entries(substitutes or []),
    }
    if description is not None:
        payload["description"] = description
    if status is not None:
        payload["status"] = status
    return client.post(
        f"/api/teams/{team_id}/lineups", json=payload, headers=headers
    )


def _lineup(client, headers, team_id, lineup_id):
    return client.get(
        f"/api/teams/{team_id}/lineups/{lineup_id}", headers=headers
    )


# ---------------------------------------------------------------------------
# Creación y serialización
# ---------------------------------------------------------------------------


def test_lineup_writes_require_authentication(client):
    captain, headers, team, members = _setup_team(client)
    lineup = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]

    calls = [
        client.post(f"/api/teams/{team['id']}/lineups", json={"name": "X"}),
        client.put(
            f"/api/teams/{team['id']}/lineups/{lineup['id']}",
            json={"name": "X"},
        ),
        client.delete(f"/api/teams/{team['id']}/lineups/{lineup['id']}"),
        client.put(
            f"/api/teams/{team['id']}/lineups/{lineup['id']}/players",
            json={"starters": []},
        ),
        client.post(
            f"/api/teams/{team['id']}/lineups/{lineup['id']}/activate"
        ),
        client.post(
            f"/api/teams/{team['id']}/lineups/{lineup['id']}/deactivate"
        ),
        client.post(
            f"/api/teams/{team['id']}/lineups/{lineup['id']}/primary"
        ),
    ]
    assert all(response.status_code == 401 for response in calls)


def test_captain_creates_lineup_with_roster_and_game_roles(client):
    captain, headers, team, members = _setup_team(
        client, total_members=7
    )
    starters = members[:5]
    substitutes = members[5:7]

    response = _create_lineup(
        client,
        headers,
        team["id"],
        description="Alineación titular",
        starters=starters,
        substitutes=substitutes,
    )

    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    lineup = body["lineup"]
    assert body["limits"] == {"starters": 5, "substitutes": 5}
    assert lineup["name"] == "Main Lineup"
    assert lineup["description"] == "Alineación titular"
    assert lineup["status"] == "DRAFT"
    assert lineup["is_primary"] is False
    assert lineup["is_complete"] is True
    assert lineup["starters_count"] == 5
    assert lineup["substitutes_count"] == 2
    assert lineup["limits"] == {"starters": 5, "substitutes": 5}
    assert [entry["user"]["id"] for entry in lineup["starters"]] == [
        member.id for member in starters
    ]
    assert [entry["user"]["id"] for entry in lineup["substitutes"]] == [
        member.id for member in substitutes
    ]
    assert lineup["permissions"]["can_edit"] is True
    assert lineup["permissions"]["can_delete"] is True
    assert lineup["permissions"]["can_set_primary"] is False
    assert lineup["created_at"] and lineup["updated_at"]

    for entry in lineup["starters"] + lineup["substitutes"]:
        user_payload = entry["user"]
        assert "email" not in user_payload
        assert "password_hash" not in user_payload
        assert "is_admin" not in user_payload

    listing = client.get(
        f"/api/teams/{team['id']}/lineups", headers=headers
    )
    assert listing.status_code == 200
    assert listing.get_json()["meta"]["total"] == 1
    assert listing.get_json()["limits"] == {
        "starters": 5,
        "substitutes": 5,
    }

    detail = _lineup(client, headers, team["id"], lineup["id"])
    assert detail.status_code == 200
    assert detail.get_json()["lineup"]["id"] == lineup["id"]

    team_payload = client.get(
        f"/api/teams/{team['id']}", headers=headers
    ).get_json()["team"]
    assert team_payload["permissions"]["can_view_lineups"] is True
    assert team_payload["permissions"]["can_manage_lineups"] is True
    assert team_payload["permissions"]["can_delete_lineups"] is True
    assert team_payload["permissions"]["can_set_primary_lineup"] is True


def test_game_roles_are_independent_per_lineup(client):
    captain, headers, team, members = _setup_team(client)
    first = _create_lineup(
        client,
        headers,
        team["id"],
        name="First",
        starters=members[:5],
    ).get_json()["lineup"]
    second = _create_lineup(
        client,
        headers,
        team["id"],
        name="Second",
        starters=members[:5],
    ).get_json()["lineup"]

    first_role = client.put(
        f"/api/teams/{team['id']}/lineups/{first['id']}/players",
        json={
            "starters": _entries(
                members[:5],
                ["IGL", "AWPER", "ENTRY", "SUPPORT", "LURKER"],
            )
        },
        headers=headers,
    )
    assert first_role.status_code == 200
    roles = [
        entry["role"]
        for entry in first_role.get_json()["lineup"]["starters"]
    ]
    assert set(roles) == {"IGL", "AWPER", "ENTRY", "SUPPORT", "LURKER"}

    second_detail = _lineup(
        client, headers, team["id"], second["id"]
    ).get_json()["lineup"]
    assert [entry["role"] for entry in second_detail["starters"]] == [
        None
    ] * 5


def test_create_lineup_validation_rules(client):
    captain, headers, team, members = _setup_team(
        client, total_members=8
    )
    outsider = _create_user("lineup-outsider")

    empty_name = client.post(
        f"/api/teams/{team['id']}/lineups",
        json={"name": ""},
        headers=headers,
    )
    assert empty_name.status_code == 400
    assert "name" in empty_name.get_json()["fields"]

    long_name = client.post(
        f"/api/teams/{team['id']}/lineups",
        json={"name": "x" * 81},
        headers=headers,
    )
    assert long_name.status_code == 400
    assert "name" in long_name.get_json()["fields"]

    invalid_status = client.post(
        f"/api/teams/{team['id']}/lineups",
        json={"name": "Bad", "status": "ARCHIVED"},
        headers=headers,
    )
    assert invalid_status.status_code == 400
    assert "status" in invalid_status.get_json()["fields"]

    non_member = _create_lineup(
        client, headers, team["id"], starters=[members[0], outsider]
    )
    assert non_member.status_code == 400
    assert "starters" in non_member.get_json()["fields"]

    duplicate = _create_lineup(
        client,
        headers,
        team["id"],
        starters=[members[0], members[0]],
    )
    assert duplicate.status_code == 400

    starter_and_sub = _create_lineup(
        client,
        headers,
        team["id"],
        starters=members[:4],
        substitutes=[members[0]],
    )
    assert starter_and_sub.status_code == 400

    too_many_starters = _create_lineup(
        client, headers, team["id"], starters=members[:6]
    )
    assert too_many_starters.status_code == 400
    assert "starters" in too_many_starters.get_json()["fields"]

    too_many_substitutes = _create_lineup(
        client, headers, team["id"], substitutes=members[:6]
    )
    assert too_many_substitutes.status_code == 400
    assert "substitutes" in too_many_substitutes.get_json()["fields"]

    invalid_role = client.post(
        f"/api/teams/{team['id']}/lineups",
        json={
            "name": "Bad role",
            "starters": [{"user_id": members[0].id, "role": "CAPTAIN"}],
        },
        headers=headers,
    )
    assert invalid_role.status_code == 400

    incomplete_active = _create_lineup(
        client,
        headers,
        team["id"],
        status="ACTIVE",
        starters=members[:4],
    )
    assert incomplete_active.status_code == 400
    assert "starters" in incomplete_active.get_json()["fields"]

    complete_active = _create_lineup(
        client,
        headers,
        team["id"],
        status="ACTIVE",
        starters=members[:5],
    )
    assert complete_active.status_code == 201
    assert complete_active.get_json()["lineup"]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------


def test_coach_can_manage_but_cannot_delete_or_set_primary(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    coach = _create_user("lineup-coach")
    _add_member(client, headers, team["id"], coach, role="COACH")
    coach_headers = _headers(coach)
    roster = members[:5]

    created = _create_lineup(
        client, coach_headers, team["id"], starters=roster
    )
    assert created.status_code == 201
    lineup_id = created.get_json()["lineup"]["id"]
    assert created.get_json()["lineup"]["permissions"]["can_delete"] is False
    assert (
        created.get_json()["lineup"]["permissions"]["can_set_primary"]
        is False
    )

    updated = client.put(
        f"/api/teams/{team['id']}/lineups/{lineup_id}",
        json={"name": "Coach lineup"},
        headers=coach_headers,
    )
    assert updated.status_code == 200
    assert updated.get_json()["lineup"]["name"] == "Coach lineup"

    replaced = client.put(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/players",
        json={
            "starters": _entries(
                members[:5],
                ["IGL", "AWPER", "ENTRY", "SUPPORT", "LURKER"],
            )
        },
        headers=coach_headers,
    )
    assert replaced.status_code == 200

    activated = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=coach_headers,
    )
    assert activated.status_code == 200
    assert activated.get_json()["lineup"]["status"] == "ACTIVE"

    denied_delete = client.delete(
        f"/api/teams/{team['id']}/lineups/{lineup_id}",
        headers=coach_headers,
    )
    assert denied_delete.status_code == 403

    denied_primary = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/primary",
        headers=coach_headers,
    )
    assert denied_primary.status_code == 403

    primary = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/primary",
        headers=headers,
    )
    assert primary.status_code == 200
    assert primary.get_json()["lineup"]["is_primary"] is True

    deleted = client.delete(
        f"/api/teams/{team['id']}/lineups/{lineup_id}", headers=headers
    )
    assert deleted.status_code == 204


def test_player_and_outsider_cannot_manage_lineups(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    player = members[1]
    outsider = _create_user("lineup-outsider-player")
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]["id"]

    calls = []
    for actor in (player, outsider):
        actor_headers = _headers(actor)
        calls.extend(
            [
                client.post(
                    f"/api/teams/{team['id']}/lineups",
                    json={"name": "Hack"},
                    headers=actor_headers,
                ),
                client.put(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}",
                    json={"name": "Hack"},
                    headers=actor_headers,
                ),
                client.put(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}/players",
                    json={"starters": []},
                    headers=actor_headers,
                ),
                client.post(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
                    headers=actor_headers,
                ),
                client.post(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}/deactivate",
                    headers=actor_headers,
                ),
                client.delete(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}",
                    headers=actor_headers,
                ),
                client.post(
                    f"/api/teams/{team['id']}/lineups/{lineup_id}/primary",
                    headers=actor_headers,
                ),
            ]
        )
    assert all(response.status_code == 403 for response in calls)

    # Un integrante puede ver las alineaciones de un equipo público.
    assert (
        client.get(
            f"/api/teams/{team['id']}/lineups",
            headers=_headers(player),
        ).status_code
        == 200
    )


def test_admin_can_manage_lineups_of_any_team(client):
    captain, headers, team, members = _setup_team(client)
    admin = _create_user("lineup-admin", is_admin=True)
    admin_headers = _headers(admin)

    created = _create_lineup(
        client, admin_headers, team["id"], starters=members[:5]
    )
    assert created.status_code == 201
    lineup_id = created.get_json()["lineup"]["id"]
    assert created.get_json()["lineup"]["permissions"]["can_delete"] is True

    activated = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=admin_headers,
    )
    assert activated.status_code == 200

    primary = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/primary",
        headers=admin_headers,
    )
    assert primary.status_code == 200
    assert primary.get_json()["lineup"]["is_primary"] is True

    deleted = client.delete(
        f"/api/teams/{team['id']}/lineups/{lineup_id}",
        headers=admin_headers,
    )
    assert deleted.status_code == 204


# ---------------------------------------------------------------------------
# Activación y lineup principal
# ---------------------------------------------------------------------------


def test_activation_requires_five_valid_starters(client):
    captain, headers, team, members = _setup_team(client)
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[:4]
    ).get_json()["lineup"]["id"]

    denied = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=headers,
    )
    assert denied.status_code == 400
    assert "starters" in denied.get_json()["fields"]

    replaced = client.put(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/players",
        json={"starters": _entries(members[:5])},
        headers=headers,
    )
    assert replaced.status_code == 200

    activated = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=headers,
    )
    assert activated.status_code == 200
    assert activated.get_json()["lineup"]["status"] == "ACTIVE"

    again = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=headers,
    )
    assert again.status_code == 200

    deactivated = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/deactivate",
        headers=headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.get_json()["lineup"]["status"] == "DRAFT"

    again_deactivated = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/deactivate",
        headers=headers,
    )
    assert again_deactivated.status_code == 200


def test_only_one_primary_lineup_and_it_must_be_active(client):
    captain, headers, team, members = _setup_team(client)
    first = _create_lineup(
        client, headers, team["id"], name="First", starters=members[:5]
    ).get_json()["lineup"]
    second = _create_lineup(
        client, headers, team["id"], name="Second", starters=members[:5]
    ).get_json()["lineup"]

    draft_primary = client.post(
        f"/api/teams/{team['id']}/lineups/{first['id']}/primary",
        headers=headers,
    )
    assert draft_primary.status_code == 400

    for lineup in (first, second):
        assert (
            client.post(
                f"/api/teams/{team['id']}/lineups/{lineup['id']}/activate",
                headers=headers,
            ).status_code
            == 200
        )

    first_primary = client.post(
        f"/api/teams/{team['id']}/lineups/{first['id']}/primary",
        headers=headers,
    )
    assert first_primary.status_code == 200
    assert first_primary.get_json()["lineup"]["is_primary"] is True

    second_primary = client.post(
        f"/api/teams/{team['id']}/lineups/{second['id']}/primary",
        headers=headers,
    )
    assert second_primary.status_code == 200
    assert second_primary.get_json()["lineup"]["is_primary"] is True

    first_detail = _lineup(
        client, headers, team["id"], first["id"]
    ).get_json()["lineup"]
    assert first_detail["is_primary"] is False
    assert (
        db.session.query(TeamLineup)
        .filter_by(team_id=team["id"], is_primary=True)
        .count()
        == 1
    )

    deactivated = client.post(
        f"/api/teams/{team['id']}/lineups/{second['id']}/deactivate",
        headers=headers,
    )
    assert deactivated.status_code == 200
    payload = deactivated.get_json()["lineup"]
    assert payload["status"] == "DRAFT"
    assert payload["is_primary"] is False
    assert (
        db.session.query(TeamLineup)
        .filter_by(team_id=team["id"], is_primary=True)
        .count()
        == 0
    )


def test_primary_rejects_lineup_with_departed_player(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    target = members[-1]
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[1:6]
    ).get_json()["lineup"]["id"]
    client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/activate",
        headers=headers,
    )

    # Simula una referencia obsoleta saltándose el servicio de equipos.
    membership = (
        db.session.query(TeamMember)
        .filter_by(team_id=team["id"], user_id=target.id)
        .one()
    )
    db.session.delete(membership)
    db.session.commit()

    response = client.post(
        f"/api/teams/{team['id']}/lineups/{lineup_id}/primary",
        headers=headers,
    )
    assert response.status_code == 409
    assert "starters" in response.get_json()["fields"]


# ---------------------------------------------------------------------------
# Reemplazo de roster
# ---------------------------------------------------------------------------


def test_replace_players_validates_limits_membership_and_duplicates(client):
    captain, headers, team, members = _setup_team(
        client, total_members=8
    )
    outsider = _create_user("lineup-roster-outsider")
    lineup = _create_lineup(
        client,
        headers,
        team["id"],
        status="ACTIVE",
        starters=members[:5],
    ).get_json()["lineup"]
    url = f"/api/teams/{team['id']}/lineups/{lineup['id']}/players"

    incomplete = client.put(
        url, json={"starters": _entries(members[:4])}, headers=headers
    )
    assert incomplete.status_code == 400
    current = _lineup(
        client, headers, team["id"], lineup["id"]
    ).get_json()["lineup"]
    assert current["starters_count"] == 5

    duplicate = client.put(
        url,
        json={
            "starters": _entries([members[0], members[0]]),
        },
        headers=headers,
    )
    assert duplicate.status_code == 400

    non_member = client.put(
        url,
        json={"starters": _entries([members[0], outsider])},
        headers=headers,
    )
    assert non_member.status_code == 400

    too_many_subs = client.put(
        url,
        json={
            "starters": _entries(members[:5]),
            "substitutes": _entries(members[:6]),
        },
        headers=headers,
    )
    assert too_many_subs.status_code == 400
    assert "substitutes" in too_many_subs.get_json()["fields"]

    replaced = client.put(
        url,
        json={
            "starters": _entries(
                members[:5],
                ["IGL", "AWPER", "ENTRY", "SUPPORT", "LURKER"],
            ),
            "substitutes": _entries(members[5:7], ["RIFLER", "FLEX"]),
        },
        headers=headers,
    )
    assert replaced.status_code == 200
    payload = replaced.get_json()["lineup"]
    assert payload["status"] == "ACTIVE"
    assert payload["starters_count"] == 5
    assert payload["substitutes_count"] == 2
    assert {entry["role"] for entry in payload["starters"]} == {
        "IGL",
        "AWPER",
        "ENTRY",
        "SUPPORT",
        "LURKER",
    }


def test_update_and_delete_lineup(client):
    captain, headers, team, members = _setup_team(client)
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]["id"]

    updated = client.put(
        f"/api/teams/{team['id']}/lineups/{lineup_id}",
        json={"name": "Roster B", "description": "Segunda alineación"},
        headers=headers,
    )
    assert updated.status_code == 200
    payload = updated.get_json()["lineup"]
    assert payload["name"] == "Roster B"
    assert payload["description"] == "Segunda alineación"

    invalid = client.put(
        f"/api/teams/{team['id']}/lineups/{lineup_id}",
        json={"name": ""},
        headers=headers,
    )
    assert invalid.status_code == 400

    missing = client.put(
        f"/api/teams/{team['id']}/lineups/99999",
        json={"name": "Missing"},
        headers=headers,
    )
    assert missing.status_code == 404

    deleted = client.delete(
        f"/api/teams/{team['id']}/lineups/{lineup_id}", headers=headers
    )
    assert deleted.status_code == 204
    assert (
        _lineup(client, headers, team["id"], lineup_id).status_code == 404
    )


# ---------------------------------------------------------------------------
# Privacidad
# ---------------------------------------------------------------------------


def test_private_team_lineups_respect_team_privacy(client):
    captain, headers, team, members = _setup_team(
        client, total_members=5, visibility="PRIVATE"
    )
    outsider = _create_user("lineup-private-outsider")
    admin = _create_user("lineup-private-admin", is_admin=True)
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]["id"]

    list_url = f"/api/teams/{team['id']}/lineups"
    detail_url = f"{list_url}/{lineup_id}"

    assert client.get(list_url).status_code == 403
    assert client.get(detail_url).status_code == 403
    assert (
        client.get(list_url, headers=_headers(outsider)).status_code == 403
    )
    assert (
        client.get(detail_url, headers=_headers(outsider)).status_code == 403
    )
    assert (
        client.get(list_url, headers=_headers(members[1])).status_code == 200
    )
    assert (
        client.get(detail_url, headers=_headers(members[1])).status_code
        == 200
    )
    assert (
        client.get(list_url, headers=_headers(admin)).status_code == 200
    )
    assert (
        client.get(detail_url, headers=_headers(admin)).status_code == 200
    )


def test_public_team_lineups_are_visible_to_anonymous(client):
    captain, headers, team, members = _setup_team(client)
    lineup_id = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]["id"]

    listing = client.get(f"/api/teams/{team['id']}/lineups")
    assert listing.status_code == 200
    assert listing.get_json()["lineups"][0]["id"] == lineup_id

    detail = client.get(
        f"/api/teams/{team['id']}/lineups/{lineup_id}"
    )
    assert detail.status_code == 200
    assert detail.get_json()["lineup"]["permissions"]["can_edit"] is False


# ---------------------------------------------------------------------------
# Integrantes que abandonan o son expulsados
# ---------------------------------------------------------------------------


def test_removed_starter_is_detached_and_active_lineup_becomes_draft(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    target = members[4]
    other_active_roster = [members[0], members[1], members[2], members[3], members[5]]
    affected = _create_lineup(
        client,
        headers,
        team["id"],
        name="Affected",
        starters=members[:5],
    ).get_json()["lineup"]
    unaffected = _create_lineup(
        client,
        headers,
        team["id"],
        name="Unaffected",
        starters=other_active_roster,
    ).get_json()["lineup"]
    for lineup in (affected, unaffected):
        assert (
            client.post(
                f"/api/teams/{team['id']}/lineups/{lineup['id']}/activate",
                headers=headers,
            ).status_code
            == 200
        )
    assert (
        client.post(
            f"/api/teams/{team['id']}/lineups/{affected['id']}/primary",
            headers=headers,
        ).status_code
        == 200
    )

    removed = client.delete(
        f"/api/teams/{team['id']}/members/{target.id}", headers=headers
    )
    assert removed.status_code == 204

    affected_payload = _lineup(
        client, headers, team["id"], affected["id"]
    ).get_json()["lineup"]
    assert affected_payload["status"] == "DRAFT"
    assert affected_payload["is_primary"] is False
    assert affected_payload["starters_count"] == 4
    assert target.id not in [
        entry["user"]["id"] for entry in affected_payload["starters"]
    ]

    unaffected_payload = _lineup(
        client, headers, team["id"], unaffected["id"]
    ).get_json()["lineup"]
    assert unaffected_payload["status"] == "ACTIVE"
    assert unaffected_payload["starters_count"] == 5

    # Al reingresar no se reincorpora automáticamente a la lineup anterior.
    _add_member(client, headers, team["id"], target)
    after_rejoin = _lineup(
        client, headers, team["id"], affected["id"]
    ).get_json()["lineup"]
    assert after_rejoin["status"] == "DRAFT"
    assert after_rejoin["starters_count"] == 4
    assert target.id not in [
        entry["user"]["id"]
        for entry in after_rejoin["starters"] + after_rejoin["substitutes"]
    ]


def test_removed_substitute_does_not_deactivate_active_lineup(client):
    captain, headers, team, members = _setup_team(
        client, total_members=7
    )
    substitute = members[5]
    lineup = _create_lineup(
        client,
        headers,
        team["id"],
        starters=members[:5],
        substitutes=[substitute],
    ).get_json()["lineup"]
    client.post(
        f"/api/teams/{team['id']}/lineups/{lineup['id']}/activate",
        headers=headers,
    )
    client.post(
        f"/api/teams/{team['id']}/lineups/{lineup['id']}/primary",
        headers=headers,
    )

    removed = client.delete(
        f"/api/teams/{team['id']}/members/{substitute.id}", headers=headers
    )
    assert removed.status_code == 204

    payload = _lineup(
        client, headers, team["id"], lineup["id"]
    ).get_json()["lineup"]
    assert payload["status"] == "ACTIVE"
    assert payload["is_primary"] is True
    assert payload["starters_count"] == 5
    assert payload["substitutes_count"] == 0


def test_leaving_member_is_detached_from_lineups(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    leaver = members[4]
    lineup = _create_lineup(
        client,
        headers,
        team["id"],
        starters=members[:5],
    ).get_json()["lineup"]
    client.post(
        f"/api/teams/{team['id']}/lineups/{lineup['id']}/activate",
        headers=headers,
    )
    client.post(
        f"/api/teams/{team['id']}/lineups/{lineup['id']}/primary",
        headers=headers,
    )

    left = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(leaver)
    )
    assert left.status_code == 204

    payload = _lineup(
        client, headers, team["id"], lineup["id"]
    ).get_json()["lineup"]
    assert payload["status"] == "DRAFT"
    assert payload["is_primary"] is False
    assert leaver.id not in [
        entry["user"]["id"] for entry in payload["starters"]
    ]


def test_solo_captain_leave_deletes_lineups_with_team(client):
    captain, headers, team, _ = _setup_team(client, total_members=1)
    lineup_id = _create_lineup(
        client, headers, team["id"], name="Solo"
    ).get_json()["lineup"]["id"]

    response = client.post(
        f"/api/teams/{team['id']}/leave", headers=headers
    )
    assert response.status_code == 204
    assert db.session.get(Team, team["id"]) is None
    assert db.session.get(TeamLineup, lineup_id) is None


# ---------------------------------------------------------------------------
# Restricciones de base de datos
# ---------------------------------------------------------------------------


def test_database_prevents_duplicate_players_and_two_primary_lineups(client):
    captain, headers, team, members = _setup_team(
        client, total_members=6
    )
    first = _create_lineup(
        client, headers, team["id"], name="First", starters=members[:5]
    ).get_json()["lineup"]
    second = _create_lineup(
        client, headers, team["id"], name="Second", starters=members[:5]
    ).get_json()["lineup"]

    db.session.add(
        TeamLineupPlayer(
            lineup_id=first["id"],
            user_id=members[0].id,
            role="IGL",
            is_starter=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(
        TeamLineupPlayer(
            lineup_id=first["id"],
            user_id=members[5].id,
            role="CAPTAIN",
            is_starter=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(
        TeamLineupPlayer(
            lineup_id=first["id"],
            user_id=members[5].id,
            role="NOT_A_ROLE",
            is_starter=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    first_model = db.session.get(TeamLineup, first["id"])
    second_model = db.session.get(TeamLineup, second["id"])
    first_model.is_primary = True
    second_model.is_primary = True
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    assert (
        db.session.query(TeamLineup)
        .filter_by(team_id=team["id"], is_primary=True)
        .count()
        == 0
    )


def test_database_prevents_invalid_status(client):
    captain, headers, team, members = _setup_team(client)
    lineup = _create_lineup(
        client, headers, team["id"], starters=members[:5]
    ).get_json()["lineup"]

    db.session.get(TeamLineup, lineup["id"]).status = "ARCHIVED"
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
