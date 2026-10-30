from types import SimpleNamespace

import pytest

from app.permissions import (
    TeamRole,
    Visibility,
    can_admin_catalog,
    can_edit,
    can_manage_team,
    can_view,
    coerce_visibility,
    is_valid_visibility,
)


def _actor(identifier=1, admin=False):
    return SimpleNamespace(id=identifier, is_admin=admin)


def test_public_is_visible_for_anonymous():
    assert can_view(None, Visibility.PUBLIC) is True


def test_private_requires_owner_or_admin():
    owner = _actor(1)
    other = _actor(2)
    admin = _actor(3, admin=True)

    assert can_view(None, Visibility.PRIVATE, owner_id=1) is False
    assert can_view(other, Visibility.PRIVATE, owner_id=1) is False
    assert can_view(owner, Visibility.PRIVATE, owner_id=1) is True
    assert can_view(admin, Visibility.PRIVATE, owner_id=1) is True


def test_team_requires_membership():
    member = _actor(1)
    outsider = _actor(2)

    assert can_view(None, Visibility.TEAM) is False
    assert can_view(outsider, Visibility.TEAM) is False
    assert can_view(member, Visibility.TEAM, is_team_member=True) is True


def test_edit_owner_and_team_roles():
    owner = _actor(1)
    other = _actor(2)

    assert can_edit(owner, owner_id=1) is True
    assert can_edit(other, owner_id=1) is False
    assert can_edit(other, team_role=TeamRole.CAPTAIN) is True
    assert can_edit(other, team_role=TeamRole.COACH) is True
    assert can_edit(other, team_role=TeamRole.PLAYER) is False


def test_catalog_requires_admin():
    assert can_admin_catalog(None) is False
    assert can_admin_catalog(_actor(admin=False)) is False
    assert can_admin_catalog(_actor(admin=True)) is True


def test_manage_team_requires_captain_or_admin():
    assert can_manage_team(None, TeamRole.CAPTAIN) is False
    assert can_manage_team(_actor(), TeamRole.COACH) is False
    assert can_manage_team(_actor(), TeamRole.CAPTAIN) is True
    assert can_manage_team(_actor(admin=True), TeamRole.PLAYER) is True


@pytest.mark.parametrize("value", ["PUBLIC", "private", "TeAm"])
def test_coerce_visibility_accepts_valid_values(value):
    assert isinstance(coerce_visibility(value), Visibility)


@pytest.mark.parametrize("value", ["", "FRIENDS", None])
def test_visibility_validation(value):
    if value is None or value == "":
        assert is_valid_visibility(value) is True
    else:
        assert is_valid_visibility(value) is False
