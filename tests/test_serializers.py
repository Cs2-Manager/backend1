from datetime import datetime, timezone
from types import SimpleNamespace

from app.serializers import (
    serialize_lineup_admin,
    serialize_lineup_public,
    serialize_map_admin,
    serialize_map_public,
    serialize_user_admin,
    serialize_user_private,
    serialize_user_public,
    serialize_workshop_map_admin,
    serialize_workshop_map_public,
)


def _user(admin=False):
    return SimpleNamespace(
        id=7,
        username="player",
        email="player@example.com",
        password_hash="super-secret-hash",
        is_admin=admin,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_public_user_never_exposes_email_or_password():
    data = serialize_user_public(_user())

    assert data["username"] == "player"
    assert "email" not in data
    assert "password_hash" not in data
    assert "is_admin" not in data


def test_private_and_admin_user_include_email_but_not_password():
    for serializer in (serialize_user_private, serialize_user_admin):
        data = serializer(_user(admin=True))
        assert data["email"] == "player@example.com"
        assert data["is_admin"] is True
        assert "password_hash" not in data


def test_map_serializers_include_callouts():
    callout = SimpleNamespace(
        id=1,
        map_id=2,
        zone_name="A",
        x_ratio=0.25,
        y_ratio=0.75,
    )
    map_obj = SimpleNamespace(
        id=2,
        name="Mirage",
        image_url="https://example.com/mirage.jpg",
        active_pool=True,
        callouts=[callout],
    )

    public = serialize_map_public(map_obj)
    admin = serialize_map_admin(map_obj)

    assert public == admin
    assert public["callouts"][0]["zone_name"] == "A"


def test_lineup_serializers_keep_current_contract():
    lineup = SimpleNamespace(
        id=3,
        map_id=2,
        type="Smoke",
        side="CT",
        title="Smoke A",
        description="Desde T",
        video_url="https://youtu.be/dQw4w9WgXcQ",
    )

    assert serialize_lineup_public(lineup) == serialize_lineup_admin(lineup)
    assert set(serialize_lineup_public(lineup)) == {
        "id",
        "map_id",
        "type",
        "side",
        "title",
        "description",
        "video_url",
    }


def test_workshop_serializers_keep_current_contract():
    item = SimpleNamespace(
        id=4,
        title="Aim Botz",
        category="Aim",
        description="Entrenamiento",
        image_url="https://example.com/aim.jpg",
        workshop_url="https://steamcommunity.com/sharedfiles/1",
    )

    assert serialize_workshop_map_public(item) == serialize_workshop_map_admin(item)
