"""Pruebas del sistema de equipos, roles, privacidad e invitaciones."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.team import Team, TeamInvitation, TeamMember
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


def _create_team(
    client,
    headers,
    *,
    name="Team One",
    tag=None,
    visibility="PUBLIC",
    **extra,
):
    payload = {"name": name, "visibility": visibility, **extra}
    if tag is not None:
        payload["tag"] = tag
    response = client.post("/api/teams", json=payload, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["team"]


def _invite(client, headers, team_id, user, *, role="PLAYER"):
    return client.post(
        f"/api/teams/{team_id}/invitations",
        json={"user_id": user.id, "role": role},
        headers=headers,
    )


def _add_member(client, captain_headers, team_id, user, *, role="PLAYER"):
    response = _invite(client, captain_headers, team_id, user, role=role)
    assert response.status_code == 201, response.get_json()
    invitation_id = response.get_json()["invitation"]["id"]
    accepted = client.post(
        f"/api/teams/invitations/{invitation_id}/accept",
        headers=_headers(user),
    )
    assert accepted.status_code == 200, accepted.get_json()
    return accepted.get_json()


def _membership(user_id):
    return db.session.query(TeamMember).filter_by(user_id=user_id).first()


# ---------------------------------------------------------------------------
# Creación y perfil
# ---------------------------------------------------------------------------


def test_create_team_requires_authentication(client):
    response = client.post("/api/teams", json={"name": "No Auth"})
    assert response.status_code == 401


def test_captain_creates_team_and_becomes_captain(client):
    captain = _create_user("captain")
    headers = _headers(captain)

    team = _create_team(
        client,
        headers,
        name="Team Alpha",
        tag="alpha",
        visibility="PUBLIC",
        description="Equipo de prueba",
        country="ar",
        logo_url="https://example.com/logo.png",
    )

    assert team["name"] == "Team Alpha"
    assert team["tag"] == "ALPHA"
    assert team["country"] == "AR"
    assert team["visibility"] == "PUBLIC"
    assert team["my_role"] == "CAPTAIN"
    assert team["is_member"] is True
    assert team["member_count"] == 1
    assert team["captain"]["id"] == captain.id
    assert team["permissions"]["can_edit"] is True
    assert team["permissions"]["can_manage_members"] is True
    assert team["permissions"]["can_manage_invitations"] is True
    assert team["permissions"]["can_transfer_captain"] is True
    assert team["permissions"]["can_leave"] is True

    membership = _membership(captain.id)
    assert membership is not None
    assert membership.team_id == team["id"]
    assert membership.role == "CAPTAIN"


def test_create_team_validates_fields(client):
    user = _create_user("validator")
    headers = _headers(user)

    response = client.post(
        "/api/teams",
        json={
            "name": "",
            "tag": "!",
            "country": "ARG",
            "visibility": "TEAM",
            "logo_url": "javascript:alert(1)",
        },
        headers=headers,
    )

    assert response.status_code == 400
    fields = response.get_json()["fields"]
    assert "name" in fields
    assert "tag" in fields
    assert "country" in fields
    assert "visibility" in fields
    assert "logo_url" in fields


def test_user_cannot_create_a_second_team(client):
    user = _create_user("single")
    headers = _headers(user)
    _create_team(client, headers, name="First")

    response = client.post(
        "/api/teams", json={"name": "Second"}, headers=headers
    )

    assert response.status_code == 409
    assert db.session.query(Team).count() == 1


def test_public_directory_only_lists_public_teams_and_searches(client):
    public_owner = _create_user("public-owner")
    private_owner = _create_user("private-owner")
    public_team = _create_team(
        client, _headers(public_owner), name="Alpha Wolves", tag="AW"
    )
    private_team = _create_team(
        client,
        _headers(private_owner),
        name="Secret Squad",
        tag="SS",
        visibility="PRIVATE",
    )

    listing = client.get("/api/teams")
    assert listing.status_code == 200
    ids = [team["id"] for team in listing.get_json()["teams"]]
    assert public_team["id"] in ids
    assert private_team["id"] not in ids

    search = client.get("/api/teams?search=wolves")
    assert [team["id"] for team in search.get_json()["teams"]] == [
        public_team["id"]
    ]

    by_tag = client.get("/api/teams?search=AW")
    assert [team["id"] for team in by_tag.get_json()["teams"]] == [
        public_team["id"]
    ]

    hidden = client.get("/api/teams?search=Secret")
    assert hidden.get_json()["teams"] == []


def test_private_team_is_only_visible_to_members_and_admins(client):
    owner = _create_user("private-captain")
    outsider = _create_user("outsider")
    admin = _create_user("admin", is_admin=True)
    team = _create_team(
        client,
        _headers(owner),
        name="Private Team",
        visibility="PRIVATE",
    )

    assert client.get(f"/api/teams/{team['id']}").status_code == 403
    assert (
        client.get(
            f"/api/teams/{team['id']}", headers=_headers(outsider)
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/teams/{team['id']}/members", headers=_headers(outsider)
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/teams/{team['id']}", headers=_headers(owner)).status_code
        == 200
    )
    assert (
        client.get(f"/api/teams/{team['id']}", headers=_headers(admin)).status_code
        == 200
    )


def test_public_team_is_visible_to_anonymous(client):
    owner = _create_user("public-captain")
    team = _create_team(client, _headers(owner), name="Open Team")

    response = client.get(f"/api/teams/{team['id']}")

    assert response.status_code == 200
    payload = response.get_json()["team"]
    assert payload["is_member"] is False
    assert payload["my_role"] is None
    assert payload["permissions"]["can_edit"] is False
    assert payload["permissions"]["can_leave"] is False
    assert "pending_invitations" not in payload


def test_update_team_permissions_and_protected_fields(client):
    captain = _create_user("edit-captain")
    outsider = _create_user("edit-outsider")
    admin = _create_user("edit-admin", is_admin=True)
    team = _create_team(
        client, _headers(captain), name="Editable", tag="EDIT"
    )

    denied = client.put(
        f"/api/teams/{team['id']}",
        json={"name": "Hacked"},
        headers=_headers(outsider),
    )
    assert denied.status_code == 403

    updated = client.put(
        f"/api/teams/{team['id']}",
        json={
            "name": "Edited",
            "tag": "NEW",
            "description": "Nueva descripción",
            "country": "uy",
            "visibility": "PRIVATE",
            "created_by_id": outsider.id,
            "id": 999,
            "member_count": 50,
        },
        headers=_headers(captain),
    )
    assert updated.status_code == 200
    payload = updated.get_json()["team"]
    assert payload["name"] == "Edited"
    assert payload["tag"] == "NEW"
    assert payload["country"] == "UY"
    assert payload["visibility"] == "PRIVATE"
    assert payload["id"] == team["id"]
    assert payload["captain"]["id"] == captain.id
    assert payload["member_count"] == 1

    as_admin = client.put(
        f"/api/teams/{team['id']}",
        json={"description": "Admin edit"},
        headers=_headers(admin),
    )
    assert as_admin.status_code == 200
    assert as_admin.get_json()["team"]["description"] == "Admin edit"


def test_update_team_rejects_duplicate_tag_and_invalid_data(client):
    first = _create_user("tag-first")
    second = _create_user("tag-second")
    _create_team(client, _headers(first), name="First", tag="SAME")
    team = _create_team(client, _headers(second), name="Second", tag="OTHER")

    duplicate = client.put(
        f"/api/teams/{team['id']}",
        json={"tag": "same"},
        headers=_headers(second),
    )
    assert duplicate.status_code == 400
    assert "tag" in duplicate.get_json()["fields"]

    invalid = client.put(
        f"/api/teams/{team['id']}",
        json={"visibility": "TEAM"},
        headers=_headers(second),
    )
    assert invalid.status_code == 400
    assert "visibility" in invalid.get_json()["fields"]


def test_coach_cannot_edit_team(client):
    captain = _create_user("coach-edit-captain")
    coach = _create_user("coach-editor")
    team = _create_team(client, _headers(captain), name="Coach Team")
    _add_member(
        client, _headers(captain), team["id"], coach, role="COACH"
    )

    response = client.put(
        f"/api/teams/{team['id']}",
        json={"description": "Coach edit"},
        headers=_headers(coach),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Invitaciones
# ---------------------------------------------------------------------------


def test_invitation_validation_rules(client):
    captain = _create_user("inv-captain")
    player = _create_user("inv-player")
    member = _create_user("inv-member")
    other_captain = _create_user("inv-other-captain")
    team = _create_team(client, _headers(captain), name="Invites")
    _add_member(client, _headers(captain), team["id"], member)
    _create_team(client, _headers(other_captain), name="Other Team")

    duplicate = _invite(client, _headers(captain), team["id"], player)
    assert duplicate.status_code == 201
    assert (
        _invite(client, _headers(captain), team["id"], player).status_code
        == 409
    )

    missing = client.post(
        f"/api/teams/{team['id']}/invitations",
        json={"user_id": 99999},
        headers=_headers(captain),
    )
    assert missing.status_code == 404

    self_invite = _invite(client, _headers(captain), team["id"], captain)
    assert self_invite.status_code == 400

    already_member = _invite(client, _headers(captain), team["id"], member)
    assert already_member.status_code == 409

    in_other_team = _invite(
        client, _headers(captain), team["id"], other_captain
    )
    assert in_other_team.status_code == 409

    captain_role = client.post(
        f"/api/teams/{team['id']}/invitations",
        json={"user_id": player.id, "role": "CAPTAIN"},
        headers=_headers(captain),
    )
    assert captain_role.status_code == 400

    by_username = client.post(
        f"/api/teams/{team['id']}/invitations",
        json={"username": "inv-player"},
        headers=_headers(captain),
    )
    assert by_username.status_code == 409


def test_player_cannot_invite_but_coach_can(client):
    captain = _create_user("invite-captain")
    player = _create_user("invite-player")
    coach = _create_user("invite-coach")
    target = _create_user("invite-target")
    team = _create_team(client, _headers(captain), name="Invite Roles")
    _add_member(client, _headers(captain), team["id"], player)
    _add_member(
        client, _headers(captain), team["id"], coach, role="COACH"
    )

    denied = _invite(client, _headers(player), team["id"], target)
    assert denied.status_code == 403

    allowed = _invite(
        client, _headers(coach), team["id"], target, role="COACH"
    )
    assert allowed.status_code == 201
    assert allowed.get_json()["invitation"]["role"] == "COACH"


def test_accept_invitation_creates_membership_and_cancels_others(client):
    captain = _create_user("accept-captain")
    other_captain = _create_user("accept-other-captain")
    player = _create_user("accept-player")
    team = _create_team(client, _headers(captain), name="Accept Team")
    other_team = _create_team(
        client, _headers(other_captain), name="Other Accept Team"
    )

    first = _invite(client, _headers(captain), team["id"], player)
    second = _invite(
        client, _headers(other_captain), other_team["id"], player
    )
    first_id = first.get_json()["invitation"]["id"]
    second_id = second.get_json()["invitation"]["id"]

    received = client.get("/api/teams/invitations", headers=_headers(player))
    assert received.status_code == 200
    assert {item["id"] for item in received.get_json()["invitations"]} == {
        first_id,
        second_id,
    }

    accepted = client.post(
        f"/api/teams/invitations/{first_id}/accept", headers=_headers(player)
    )
    assert accepted.status_code == 200
    body = accepted.get_json()
    assert body["team"]["id"] == team["id"]
    assert body["invitation"]["status"] == "ACCEPTED"
    assert _membership(player.id).team_id == team["id"]
    assert _membership(player.id).role == "PLAYER"

    other = db.session.get(TeamInvitation, second_id)
    assert other.status == "CANCELLED"

    again = client.post(
        f"/api/teams/invitations/{first_id}/accept", headers=_headers(player)
    )
    assert again.status_code == 409

    my_team = client.get("/api/teams/mine", headers=_headers(player))
    assert my_team.status_code == 200
    assert my_team.get_json()["team"]["id"] == team["id"]


def test_accept_invitation_requires_owner_and_pending_status(client):
    captain = _create_user("accept-owner-captain")
    player = _create_user("accept-owner-player")
    intruder = _create_user("accept-intruder")
    team = _create_team(client, _headers(captain), name="Owned Invite")
    invitation_id = _invite(
        client, _headers(captain), team["id"], player
    ).get_json()["invitation"]["id"]

    foreign = client.post(
        f"/api/teams/invitations/{invitation_id}/accept",
        headers=_headers(intruder),
    )
    assert foreign.status_code == 403

    rejected = client.post(
        f"/api/teams/invitations/{invitation_id}/reject",
        headers=_headers(player),
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["invitation"]["status"] == "REJECTED"

    after_reject = client.post(
        f"/api/teams/invitations/{invitation_id}/accept",
        headers=_headers(player),
    )
    assert after_reject.status_code == 409


def test_accepting_two_invitations_only_allows_one_team(client):
    first_captain = _create_user("race-first-captain")
    second_captain = _create_user("race-second-captain")
    player = _create_user("race-player")
    first_team = _create_team(
        client, _headers(first_captain), name="Race First"
    )
    second_team = _create_team(
        client, _headers(second_captain), name="Race Second"
    )
    first_id = _invite(
        client, _headers(first_captain), first_team["id"], player
    ).get_json()["invitation"]["id"]
    second_id = _invite(
        client, _headers(second_captain), second_team["id"], player
    ).get_json()["invitation"]["id"]

    first_accept = client.post(
        f"/api/teams/invitations/{first_id}/accept", headers=_headers(player)
    )
    second_accept = client.post(
        f"/api/teams/invitations/{second_id}/accept", headers=_headers(player)
    )

    assert first_accept.status_code == 200
    assert second_accept.status_code == 409
    assert db.session.query(TeamMember).filter_by(user_id=player.id).count() == 1


def test_accept_invitation_when_already_in_a_team(client):
    first_captain = _create_user("already-first")
    second_captain = _create_user("already-second")
    player = _create_user("already-player")
    first_team = _create_team(
        client, _headers(first_captain), name="Already First"
    )
    second_team = _create_team(
        client, _headers(second_captain), name="Already Second"
    )
    _add_member(client, _headers(first_captain), first_team["id"], player)

    invitation = TeamInvitation(
        team_id=second_team["id"],
        user_id=player.id,
        invited_by_id=second_captain.id,
        role="PLAYER",
        status="PENDING",
    )
    db.session.add(invitation)
    db.session.commit()

    response = client.post(
        f"/api/teams/invitations/{invitation.id}/accept",
        headers=_headers(player),
    )
    assert response.status_code == 409
    assert db.session.query(TeamMember).filter_by(user_id=player.id).count() == 1


def test_reject_and_reinvite_after_rejection(client):
    captain = _create_user("reject-captain")
    player = _create_user("reject-player")
    team = _create_team(client, _headers(captain), name="Reject Team")
    invitation_id = _invite(
        client, _headers(captain), team["id"], player
    ).get_json()["invitation"]["id"]

    rejected = client.post(
        f"/api/teams/invitations/{invitation_id}/reject",
        headers=_headers(player),
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["invitation"]["status"] == "REJECTED"

    reinvite = _invite(client, _headers(captain), team["id"], player)
    assert reinvite.status_code == 201


def test_cancel_invitation_permissions(client):
    captain = _create_user("cancel-captain")
    coach = _create_user("cancel-coach")
    player = _create_user("cancel-player")
    target = _create_user("cancel-target")
    other_target = _create_user("cancel-other-target")
    team = _create_team(client, _headers(captain), name="Cancel Team")
    _add_member(client, _headers(captain), team["id"], coach, role="COACH")
    _add_member(client, _headers(captain), team["id"], player)

    coach_invite = _invite(
        client, _headers(coach), team["id"], target
    ).get_json()["invitation"]["id"]
    captain_invite = _invite(
        client, _headers(captain), team["id"], other_target
    ).get_json()["invitation"]["id"]

    denied = client.delete(
        f"/api/teams/{team['id']}/invitations/{captain_invite}",
        headers=_headers(coach),
    )
    assert denied.status_code == 403

    cancelled = client.delete(
        f"/api/teams/{team['id']}/invitations/{coach_invite}",
        headers=_headers(coach),
    )
    assert cancelled.status_code == 204

    player_denied = client.delete(
        f"/api/teams/{team['id']}/invitations/{captain_invite}",
        headers=_headers(player),
    )
    assert player_denied.status_code == 403

    captain_cancelled = client.delete(
        f"/api/teams/{team['id']}/invitations/{captain_invite}",
        headers=_headers(captain),
    )
    assert captain_cancelled.status_code == 204

    again = client.delete(
        f"/api/teams/{team['id']}/invitations/{captain_invite}",
        headers=_headers(captain),
    )
    assert again.status_code == 409


def test_team_invitations_are_private_to_managers(client):
    captain = _create_user("list-inv-captain")
    coach = _create_user("list-inv-coach")
    player = _create_user("list-inv-player")
    outsider = _create_user("list-inv-outsider")
    team = _create_team(
        client,
        _headers(captain),
        name="Invitation Privacy",
        visibility="PRIVATE",
    )
    _add_member(client, _headers(captain), team["id"], coach, role="COACH")
    _add_member(client, _headers(captain), team["id"], player)

    assert (
        client.get(
            f"/api/teams/{team['id']}/invitations",
            headers=_headers(outsider),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/teams/{team['id']}/invitations", headers=_headers(player)
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/teams/{team['id']}/invitations", headers=_headers(coach)
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/teams/{team['id']}/invitations", headers=_headers(captain)
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Integrantes, roles y abandono
# ---------------------------------------------------------------------------


def test_remove_member_permissions(client):
    captain = _create_user("remove-captain")
    coach = _create_user("remove-coach")
    player = _create_user("remove-player")
    target = _create_user("remove-target")
    team = _create_team(client, _headers(captain), name="Remove Team")
    _add_member(client, _headers(captain), team["id"], coach, role="COACH")
    _add_member(client, _headers(captain), team["id"], player)
    _add_member(client, _headers(captain), team["id"], target)

    assert (
        client.delete(
            f"/api/teams/{team['id']}/members/{target.id}",
            headers=_headers(coach),
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/teams/{team['id']}/members/{target.id}",
            headers=_headers(player),
        ).status_code
        == 403
    )

    self_remove = client.delete(
        f"/api/teams/{team['id']}/members/{captain.id}",
        headers=_headers(captain),
    )
    assert self_remove.status_code == 400

    removed = client.delete(
        f"/api/teams/{team['id']}/members/{target.id}",
        headers=_headers(captain),
    )
    assert removed.status_code == 204
    assert _membership(target.id) is None


def test_cannot_remove_captain(client):
    captain = _create_user("captain-remove-captain")
    admin = _create_user("captain-remove-admin", is_admin=True)
    team = _create_team(client, _headers(captain), name="Captain Remove")

    response = client.delete(
        f"/api/teams/{team['id']}/members/{captain.id}",
        headers=_headers(admin),
    )
    assert response.status_code == 409


def test_role_assignment_permissions_and_rules(client):
    captain = _create_user("role-captain")
    coach = _create_user("role-coach")
    player = _create_user("role-player")
    team = _create_team(client, _headers(captain), name="Role Team")
    _add_member(client, _headers(captain), team["id"], coach, role="COACH")
    _add_member(client, _headers(captain), team["id"], player)

    promoted = client.patch(
        f"/api/teams/{team['id']}/members/{player.id}",
        json={"role": "COACH"},
        headers=_headers(captain),
    )
    assert promoted.status_code == 200
    assert promoted.get_json()["member"]["role"] == "COACH"

    coach_denied = client.patch(
        f"/api/teams/{team['id']}/members/{coach.id}",
        json={"role": "PLAYER"},
        headers=_headers(coach),
    )
    assert coach_denied.status_code == 403

    player_denied = client.patch(
        f"/api/teams/{team['id']}/members/{player.id}",
        json={"role": "PLAYER"},
        headers=_headers(player),
    )
    assert player_denied.status_code == 403

    self_change = client.patch(
        f"/api/teams/{team['id']}/members/{captain.id}",
        json={"role": "PLAYER"},
        headers=_headers(captain),
    )
    assert self_change.status_code == 400

    assign_captain = client.patch(
        f"/api/teams/{team['id']}/members/{coach.id}",
        json={"role": "CAPTAIN"},
        headers=_headers(captain),
    )
    assert assign_captain.status_code == 400


def test_transfer_captain(client):
    captain = _create_user("transfer-captain")
    player = _create_user("transfer-player")
    outsider = _create_user("transfer-outsider")
    team = _create_team(client, _headers(captain), name="Transfer Team")
    _add_member(client, _headers(captain), team["id"], player)

    denied = client.post(
        f"/api/teams/{team['id']}/transfer-captain",
        json={"user_id": captain.id},
        headers=_headers(player),
    )
    assert denied.status_code == 403

    self_transfer = client.post(
        f"/api/teams/{team['id']}/transfer-captain",
        json={"user_id": captain.id},
        headers=_headers(captain),
    )
    assert self_transfer.status_code == 400

    missing = client.post(
        f"/api/teams/{team['id']}/transfer-captain",
        json={"user_id": outsider.id},
        headers=_headers(captain),
    )
    assert missing.status_code == 404

    transferred = client.post(
        f"/api/teams/{team['id']}/transfer-captain",
        json={"user_id": player.id},
        headers=_headers(captain),
    )
    assert transferred.status_code == 200
    payload = transferred.get_json()["team"]
    assert payload["captain"]["id"] == player.id
    assert payload["my_role"] == "PLAYER"

    assert (
        client.put(
            f"/api/teams/{team['id']}",
            json={"description": "Old captain edit"},
            headers=_headers(captain),
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/teams/{team['id']}",
            json={"description": "New captain edit"},
            headers=_headers(player),
        ).status_code
        == 200
    )


def test_leave_team_and_rejoin_another(client):
    captain = _create_user("leave-captain")
    player = _create_user("leave-player")
    other_captain = _create_user("leave-other-captain")
    team = _create_team(client, _headers(captain), name="Leave Team")
    other_team = _create_team(
        client, _headers(other_captain), name="Leave Other Team"
    )
    _add_member(client, _headers(captain), team["id"], player)

    left = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(player)
    )
    assert left.status_code == 204
    assert _membership(player.id) is None

    joined = _invite(client, _headers(other_captain), other_team["id"], player)
    assert joined.status_code == 201
    invitation_id = joined.get_json()["invitation"]["id"]
    accepted = client.post(
        f"/api/teams/invitations/{invitation_id}/accept",
        headers=_headers(player),
    )
    assert accepted.status_code == 200


def test_captain_cannot_leave_until_transferring_captaincy(client):
    captain = _create_user("leave-captain-2")
    player = _create_user("leave-player-2")
    team = _create_team(client, _headers(captain), name="Captain Leave")
    _add_member(client, _headers(captain), team["id"], player)

    denied = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(captain)
    )
    assert denied.status_code == 409

    client.post(
        f"/api/teams/{team['id']}/transfer-captain",
        json={"user_id": player.id},
        headers=_headers(captain),
    )
    left = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(captain)
    )
    assert left.status_code == 204


def test_solo_captain_leave_deletes_empty_team(client):
    captain = _create_user("solo-captain")
    team = _create_team(client, _headers(captain), name="Solo Team")

    response = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(captain)
    )

    assert response.status_code == 204
    assert db.session.get(Team, team["id"]) is None
    assert _membership(captain.id) is None


def test_non_member_cannot_leave(client):
    captain = _create_user("leave-owner")
    outsider = _create_user("leave-outsider")
    team = _create_team(client, _headers(captain), name="Leave Guard")

    response = client.post(
        f"/api/teams/{team['id']}/leave", headers=_headers(outsider)
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Autorización general y privacidad de la serialización
# ---------------------------------------------------------------------------


def test_team_writes_require_authentication(client):
    captain = _create_user("authz-captain")
    team = _create_team(client, _headers(captain), name="Authz Team")
    calls = [
        client.post("/api/teams", json={"name": "Anon"}),
        client.put(f"/api/teams/{team['id']}", json={"name": "Anon"}),
        client.post(
            f"/api/teams/{team['id']}/invitations", json={"user_id": 1}
        ),
        client.get(f"/api/teams/{team['id']}/invitations"),
        client.delete(f"/api/teams/{team['id']}/invitations/1"),
        client.post("/api/teams/invitations/1/accept"),
        client.post("/api/teams/invitations/1/reject"),
        client.delete(f"/api/teams/{team['id']}/members/1"),
        client.patch(
            f"/api/teams/{team['id']}/members/1", json={"role": "COACH"}
        ),
        client.post(f"/api/teams/{team['id']}/leave"),
        client.post(
            f"/api/teams/{team['id']}/transfer-captain", json={"user_id": 1}
        ),
    ]
    assert all(response.status_code == 401 for response in calls)


def test_non_member_cannot_manage_team(client):
    captain = _create_user("authz-owner")
    outsider = _create_user("authz-outsider")
    team = _create_team(client, _headers(captain), name="Authz Private")
    headers = _headers(outsider)

    calls = [
        client.put(
            f"/api/teams/{team['id']}", json={"name": "Hack"}, headers=headers
        ),
        client.post(
            f"/api/teams/{team['id']}/invitations",
            json={"user_id": captain.id},
            headers=headers,
        ),
        client.get(
            f"/api/teams/{team['id']}/invitations", headers=headers
        ),
        client.delete(
            f"/api/teams/{team['id']}/invitations/1", headers=headers
        ),
        client.delete(
            f"/api/teams/{team['id']}/members/{captain.id}", headers=headers
        ),
        client.patch(
            f"/api/teams/{team['id']}/members/{captain.id}",
            json={"role": "PLAYER"},
            headers=headers,
        ),
        client.post(f"/api/teams/{team['id']}/leave", headers=headers),
        client.post(
            f"/api/teams/{team['id']}/transfer-captain",
            json={"user_id": captain.id},
            headers=headers,
        ),
    ]
    assert all(response.status_code == 403 for response in calls)


def test_my_team_returns_null_without_membership(client):
    user = _create_user("no-team")
    response = client.get("/api/teams/mine", headers=_headers(user))
    assert response.status_code == 200
    assert response.get_json()["team"] is None


def test_team_serialization_never_exposes_private_user_data(client):
    captain = _create_user("serialize-captain")
    player = _create_user("serialize-player")
    team = _create_team(client, _headers(captain), name="Serialize Team")
    invitation = _invite(
        client, _headers(captain), team["id"], player
    ).get_json()["invitation"]

    for user_payload in (
        team["captain"],
        team["members"][0]["user"],
        invitation["user"],
        invitation["invited_by"],
    ):
        assert "email" not in user_payload
        assert "password_hash" not in user_payload
        assert "is_admin" not in user_payload


# ---------------------------------------------------------------------------
# Restricciones de base de datos
# ---------------------------------------------------------------------------


def test_database_prevents_two_active_teams_for_same_user(client):
    first_captain = _create_user("db-first")
    second_captain = _create_user("db-second")
    first_team = _create_team(
        client, _headers(first_captain), name="DB First"
    )
    second_team = _create_team(
        client, _headers(second_captain), name="DB Second"
    )

    db.session.add(
        TeamMember(
            team_id=second_team["id"],
            user_id=first_captain.id,
            role="PLAYER",
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    assert (
        db.session.query(TeamMember)
        .filter_by(user_id=first_captain.id)
        .count()
        == 1
    )
    assert first_team["id"] != second_team["id"]


def test_database_prevents_duplicate_captains_and_pending_invitations(client):
    captain = _create_user("db-captain")
    player = _create_user("db-player")
    team = _create_team(client, _headers(captain), name="DB Rules")

    db.session.add(
        TeamMember(team_id=team["id"], user_id=player.id, role="CAPTAIN")
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(
        TeamInvitation(
            team_id=team["id"],
            user_id=player.id,
            invited_by_id=captain.id,
            role="PLAYER",
            status="PENDING",
        )
    )
    db.session.commit()
    db.session.add(
        TeamInvitation(
            team_id=team["id"],
            user_id=player.id,
            invited_by_id=captain.id,
            role="PLAYER",
            status="PENDING",
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
