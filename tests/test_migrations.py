"""Pruebas de las migraciones Alembic contra PostgreSQL real.

Requieren `TEST_POSTGRES_URL` apuntando a una base desechable. Sin esa variable
las pruebas se omiten para no afectar la suite SQLite habitual.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db_bootstrap import (
    BASELINE_REVISION,
    DatabaseState,
    IncompatibleDatabaseError,
    bootstrap_database,
    classify_database,
)

BACK_DIR = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
BASELINE = "1d65f5c82647"

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="TEST_POSTGRES_URL no configurada"
)

LEGACY_TABLES = ("lineups", "callouts", "workshop_maps", "users", "maps")
NEW_TABLES = (
    "player_profiles",
    "player_competitive_profiles",
    "player_stats",
    "player_social_links",
    "player_matches",
    "player_map_stats",
)
TEAM_TABLES = (
    "team_invitations",
    "team_lineup_players",
    "team_lineups",
    "team_members",
    "teams",
)
TABLES = LEGACY_TABLES + NEW_TABLES + TEAM_TABLES
BACKFILLED_TABLES = (
    "player_profiles",
    "player_competitive_profiles",
    "player_stats",
)
EMPTY_NEW_TABLES = (
    "player_social_links",
    "player_matches",
    "player_map_stats",
)


def _run_alembic(*args):
    env = os.environ.copy()
    env["DATABASE_URL"] = POSTGRES_URL
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACK_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def _engine():
    return create_engine(POSTGRES_URL)


def _reset_schema():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        for table in TABLES:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
    engine.dispose()


def _table_names():
    engine = _engine()
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    return names


def _head_revision():
    return _run_alembic("heads").stdout.split()[0]


def _classify():
    engine = _engine()
    try:
        return classify_database(engine)
    finally:
        engine.dispose()


def _drop_alembic_version():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()


def _seed_legacy_data():
    """Datos representativos de una instalación anterior a Alembic."""
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (username, email, password_hash, created_at) "
                "VALUES ('legacy', 'legacy@example.com', 'hash', NOW())"
            )
        )
        map_id = connection.execute(
            text(
                "INSERT INTO maps (name, image_url, active_pool) "
                "VALUES ('Mirage', 'https://example.com/mirage.jpg', true) "
                "RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO callouts (map_id, zone_name, x_ratio, y_ratio) "
                "VALUES (:map_id, 'A', 0.25, 0.75)"
            ),
            {"map_id": map_id},
        )
        connection.execute(
            text(
                "INSERT INTO lineups "
                "(map_id, type, side, title, description, video_url) "
                "VALUES (:map_id, 'Smoke', 'CT', 'Smoke A', '', "
                "'https://youtu.be/dQw4w9WgXcQ')"
            ),
            {"map_id": map_id},
        )
        connection.execute(
            text(
                "INSERT INTO workshop_maps "
                "(title, category, description, image_url, workshop_url) "
                "VALUES ('Aim Botz', 'Aim', '', 'https://example.com/aim.jpg', "
                "'https://steamcommunity.com/sharedfiles/1')"
            )
        )
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database():
    _reset_schema()
    yield
    _reset_schema()


def test_upgrade_and_downgrade_roundtrip():
    _run_alembic("upgrade", "head")
    assert set(TABLES).issubset(_table_names())

    engine = _engine()
    with engine.connect() as connection:
        is_admin = connection.execute(
            text(
                "SELECT column_default, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'is_admin'"
            )
        ).one()
    engine.dispose()

    assert is_admin.column_default == "false"
    assert is_admin.is_nullable == "NO"

    _run_alembic("downgrade", "base")
    assert not set(TABLES) & _table_names()

    _run_alembic("upgrade", "head")
    assert set(TABLES).issubset(_table_names())

    current = _run_alembic("current").stdout
    assert _head_revision() in current


def test_existing_database_is_adopted_with_stamp_and_keeps_data():
    # Simula una base creada antes de Alembic: esquema baseline sin versión.
    _run_alembic("upgrade", BASELINE)
    _drop_alembic_version()
    _seed_legacy_data()

    _run_alembic("stamp", BASELINE)
    _run_alembic("upgrade", "head")

    engine = _engine()
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT username, is_admin FROM users WHERE username = 'legacy'")
        ).one()
        counts = {
            table: connection.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one()
            for table in TABLES
        }
    engine.dispose()

    assert row.username == "legacy"
    assert row.is_admin is False
    assert counts == {
        **{table: 1 for table in LEGACY_TABLES},
        **{table: 1 for table in BACKFILLED_TABLES},
        **{table: 0 for table in EMPTY_NEW_TABLES},
        **{table: 0 for table in TEAM_TABLES},
    }


def test_bootstrap_initializes_empty_database_and_is_idempotent():
    assert _classify().state is DatabaseState.EMPTY

    classification = bootstrap_database(POSTGRES_URL)

    assert classification.state is DatabaseState.EMPTY
    assert set(TABLES).issubset(_table_names())
    assert _head_revision() in _run_alembic("current").stdout

    # Un segundo arranque ya encuentra una base gestionada por Alembic.
    second = bootstrap_database(POSTGRES_URL)
    assert second.state is DatabaseState.MANAGED
    assert set(TABLES).issubset(_table_names())


def test_bootstrap_adopts_preexisting_baseline_database_and_keeps_data():
    _run_alembic("upgrade", BASELINE)
    _drop_alembic_version()
    _seed_legacy_data()

    assert _classify().state is DatabaseState.ADOPTABLE

    classification = bootstrap_database(POSTGRES_URL)

    assert classification.state is DatabaseState.ADOPTABLE
    assert set(TABLES).issubset(_table_names())
    assert _head_revision() in _run_alembic("current").stdout

    engine = _engine()
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT username, is_admin FROM users WHERE username = 'legacy'")
        ).one()
        counts = {
            table: connection.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one()
            for table in TABLES
        }
    engine.dispose()

    assert row.username == "legacy"
    assert row.is_admin is False
    assert counts == {
        **{table: 1 for table in LEGACY_TABLES},
        **{table: 1 for table in BACKFILLED_TABLES},
        **{table: 0 for table in EMPTY_NEW_TABLES},
        **{table: 0 for table in TEAM_TABLES},
    }


def test_bootstrap_adopts_baseline_with_empty_alembic_version_table():
    _run_alembic("upgrade", BASELINE)
    _drop_alembic_version()

    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
    engine.dispose()

    assert _classify().state is DatabaseState.ADOPTABLE

    classification = bootstrap_database(POSTGRES_URL)

    assert classification.state is DatabaseState.ADOPTABLE
    assert _head_revision() in _run_alembic("current").stdout


def test_bootstrap_refuses_incompatible_schema_without_modifying_it():
    _run_alembic("upgrade", BASELINE)
    _drop_alembic_version()

    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE maps ADD COLUMN legacy_extra VARCHAR(10)")
        )
        connection.execute(
            text(
                "INSERT INTO users (username, email, password_hash, created_at) "
                "VALUES ('legacy', 'legacy@example.com', 'hash', NOW())"
            )
        )
    engine.dispose()

    classification = _classify()
    assert classification.state is DatabaseState.INCOMPATIBLE
    assert any("legacy_extra" in detail for detail in classification.details)

    with pytest.raises(IncompatibleDatabaseError):
        bootstrap_database(POSTGRES_URL)

    # No se creó la versión de Alembic ni las tablas nuevas, y el dato sigue ahí.
    assert "alembic_version" not in _table_names()
    assert "player_profiles" not in _table_names()

    engine = _engine()
    with engine.connect() as connection:
        username = connection.execute(
            text("SELECT username FROM users")
        ).scalar_one()
        extra_column = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'maps' AND column_name = 'legacy_extra'"
            )
        ).scalar_one()
    engine.dispose()

    assert username == "legacy"
    assert extra_column == "legacy_extra"


def test_bootstrap_refuses_schema_with_type_or_index_differences():
    _run_alembic("upgrade", BASELINE)
    _drop_alembic_version()

    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE maps ALTER COLUMN name TYPE VARCHAR(100)")
        )
        connection.execute(text("DROP INDEX ix_users_email"))
    engine.dispose()

    classification = _classify()
    assert classification.state is DatabaseState.INCOMPATIBLE
    assert any(
        "maps.name" in detail and "tipo distinto" in detail
        for detail in classification.details
    )
    assert any("ix_users_email" in detail for detail in classification.details)

    with pytest.raises(IncompatibleDatabaseError):
        bootstrap_database(POSTGRES_URL)

    assert "alembic_version" not in _table_names()
    assert "player_profiles" not in _table_names()


def test_bootstrap_rejects_managed_database_missing_baseline_tables():
    _run_alembic("upgrade", "head")

    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE lineups CASCADE"))
    engine.dispose()

    classification = _classify()
    assert classification.state is DatabaseState.INCOMPATIBLE
    assert any("lineups" in detail for detail in classification.details)

    with pytest.raises(IncompatibleDatabaseError):
        bootstrap_database(POSTGRES_URL)

    # La versión registrada no se altera y el resto del esquema sigue intacto.
    assert "alembic_version" in _table_names()
    assert "player_profiles" in _table_names()
    assert "lineups" not in _table_names()
