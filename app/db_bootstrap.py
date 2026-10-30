"""Arranque seguro de la base de datos con Alembic.

El contenedor no puede ejecutar siempre ``alembic upgrade head``: una base
creada antes de incorporar Alembic ya contiene las tablas del baseline pero no
tiene ``alembic_version``. En ese caso el baseline fallaría con
``DuplicateTable``.

Este módulo clasifica el esquema antes de migrar:

* ``EMPTY``: no hay tablas de la aplicación. Se ejecuta ``upgrade head``.
* ``ADOPTABLE``: el esquema coincide exactamente con el baseline y no hay
  versión registrada. Se marca el baseline y después se aplican las
  migraciones pendientes.
* ``MANAGED``: ya existe una versión de Alembic. Se ejecuta ``upgrade head``.
* ``INCOMPATIBLE``: el esquema no coincide con el baseline (tablas parciales,
  columnas o índices distintos, etc.). Se aborta sin modificar nada.

La adopción nunca se basa en el error de una migración: se decide comparando
el esquema real con el contrato del baseline antes de ejecutar Alembic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.config import Config

BACK_DIR = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "1d65f5c82647"
ALEMBIC_VERSION_TABLE = "alembic_version"


class DatabaseState(str, Enum):
    EMPTY = "empty"
    ADOPTABLE = "adoptable"
    MANAGED = "managed"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class Classification:
    state: DatabaseState
    reason: str
    details: tuple[str, ...] = ()


class BootstrapError(RuntimeError):
    """Error controlado durante el arranque de la base de datos."""


class IncompatibleDatabaseError(BootstrapError):
    """El esquema existente no se puede adoptar de forma segura."""


@dataclass(frozen=True)
class TableSpec:
    columns: Mapping[str, tuple[sa.types.TypeEngine, bool]]
    primary_key: tuple[str, ...]
    indexes: Mapping[str, tuple[tuple[str, ...], bool]]
    foreign_keys: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = ()


# Contrato exacto del baseline 1d65f5c82647. Se usa para verificar que una
# base preexistente es realmente el esquema original antes de marcarla como
# migrada. No se compara con los modelos actuales porque el head incluye
# columnas y tablas posteriores.
BASELINE_SCHEMA: Mapping[str, TableSpec] = {
    "maps": TableSpec(
        columns={
            "id": (sa.Integer(), False),
            "name": (sa.String(length=80), False),
            "image_url": (sa.String(length=500), False),
            "active_pool": (sa.Boolean(), False),
        },
        primary_key=("id",),
        indexes={"ix_maps_name": (("name",), True)},
    ),
    "users": TableSpec(
        columns={
            "id": (sa.Integer(), False),
            "username": (sa.String(length=80), False),
            "email": (sa.String(length=120), False),
            "password_hash": (sa.String(length=128), False),
            "created_at": (sa.DateTime(), False),
        },
        primary_key=("id",),
        indexes={
            "ix_users_email": (("email",), True),
            "ix_users_username": (("username",), True),
        },
    ),
    "workshop_maps": TableSpec(
        columns={
            "id": (sa.Integer(), False),
            "title": (sa.String(length=160), False),
            "category": (sa.String(length=20), False),
            "description": (sa.Text(), False),
            "image_url": (sa.String(length=500), False),
            "workshop_url": (sa.String(length=500), False),
        },
        primary_key=("id",),
        indexes={
            "ix_workshop_maps_category": (("category",), False),
            "ix_workshop_maps_title": (("title",), False),
        },
    ),
    "callouts": TableSpec(
        columns={
            "id": (sa.Integer(), False),
            "map_id": (sa.Integer(), False),
            "zone_name": (sa.String(length=120), False),
            "x_ratio": (sa.Float(), False),
            "y_ratio": (sa.Float(), False),
        },
        primary_key=("id",),
        indexes={"ix_callouts_map_id": (("map_id",), False)},
        foreign_keys=((("map_id",), "maps", ("id",)),),
    ),
    "lineups": TableSpec(
        columns={
            "id": (sa.Integer(), False),
            "map_id": (sa.Integer(), False),
            "type": (sa.String(length=20), False),
            "side": (sa.String(length=4), False),
            "title": (sa.String(length=160), False),
            "description": (sa.Text(), False),
            "video_url": (sa.String(length=500), False),
        },
        primary_key=("id",),
        indexes={
            "ix_lineups_map_id": (("map_id",), False),
            "ix_lineups_side": (("side",), False),
            "ix_lineups_type": (("type",), False),
        },
        foreign_keys=((("map_id",), "maps", ("id",)),),
    ),
}


def _type_matches(actual: sa.types.TypeEngine, expected: sa.types.TypeEngine) -> bool:
    """Compara tipos entre dialectos sin depender del nombre SQL exacto."""
    if isinstance(expected, sa.Text):
        return isinstance(actual, sa.Text)
    if isinstance(expected, sa.String):
        return (
            isinstance(actual, sa.String)
            and not isinstance(actual, sa.Text)
            and actual.length == expected.length
        )
    if isinstance(expected, sa.Boolean):
        return isinstance(actual, sa.Boolean)
    if isinstance(expected, sa.DateTime):
        return isinstance(actual, sa.DateTime)
    if isinstance(expected, sa.Float):
        return isinstance(actual, sa.Float)
    if isinstance(expected, sa.Integer):
        return isinstance(actual, sa.Integer) and not isinstance(actual, sa.Boolean)
    return isinstance(actual, type(expected))


def _schema_differences(inspector, tables: set[str]) -> list[str]:
    """Devuelve una lista legible de diferencias respecto al baseline."""
    problems: list[str] = []
    expected_tables = set(BASELINE_SCHEMA)

    for table in sorted(expected_tables - tables):
        problems.append(f"falta la tabla '{table}'")
    for table in sorted(tables - expected_tables):
        problems.append(f"tabla inesperada '{table}'")

    for table in sorted(expected_tables & tables):
        spec = BASELINE_SCHEMA[table]

        actual_columns = {
            column["name"]: column for column in inspector.get_columns(table)
        }
        expected_columns = set(spec.columns)
        for name in sorted(expected_columns - set(actual_columns)):
            problems.append(f"falta la columna '{table}.{name}'")
        for name in sorted(set(actual_columns) - expected_columns):
            problems.append(f"columna inesperada '{table}.{name}'")

        for name in sorted(expected_columns & set(actual_columns)):
            expected_type, expected_nullable = spec.columns[name]
            actual = actual_columns[name]
            if not _type_matches(actual["type"], expected_type):
                problems.append(
                    f"tipo distinto en '{table}.{name}': "
                    f"esperado {expected_type!r}, encontrado {actual['type']!r}"
                )
            if bool(actual["nullable"]) != expected_nullable:
                problems.append(
                    f"nullabilidad distinta en '{table}.{name}': "
                    f"esperado nullable={expected_nullable}, "
                    f"encontrado nullable={bool(actual['nullable'])}"
                )

        actual_pk = tuple(inspector.get_pk_constraint(table)["constrained_columns"])
        if actual_pk != spec.primary_key:
            problems.append(
                f"clave primaria distinta en '{table}': "
                f"esperado {spec.primary_key}, encontrado {actual_pk}"
            )

        actual_indexes = {
            index["name"]: (tuple(index["column_names"]), bool(index["unique"]))
            for index in inspector.get_indexes(table)
        }
        for name in sorted(set(spec.indexes) - set(actual_indexes)):
            problems.append(f"falta el índice '{name}' en '{table}'")
        for name in sorted(set(actual_indexes) - set(spec.indexes)):
            problems.append(f"índice inesperado '{name}' en '{table}'")
        for name in sorted(set(spec.indexes) & set(actual_indexes)):
            if actual_indexes[name] != spec.indexes[name]:
                problems.append(
                    f"índice distinto '{name}' en '{table}': "
                    f"esperado {spec.indexes[name]}, "
                    f"encontrado {actual_indexes[name]}"
                )

        actual_fks = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
            )
            for fk in inspector.get_foreign_keys(table)
        }
        expected_fks = set(spec.foreign_keys)
        for fk in sorted(expected_fks - actual_fks):
            problems.append(f"falta la clave foránea {fk} en '{table}'")
        for fk in sorted(actual_fks - expected_fks):
            problems.append(f"clave foránea inesperada {fk} en '{table}'")

    return problems


def _applied_revisions(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(f'SELECT version_num FROM "{ALEMBIC_VERSION_TABLE}"')
        )
        return tuple(str(row[0]) for row in rows)


def classify_database(engine: Engine) -> Classification:
    """Clasifica el estado del esquema sin modificarlo."""
    inspector = inspect(engine)
    all_tables = set(inspector.get_table_names())
    user_tables = all_tables - {ALEMBIC_VERSION_TABLE}

    revisions: tuple[str, ...] = ()
    if ALEMBIC_VERSION_TABLE in all_tables:
        revisions = _applied_revisions(engine)

    if revisions:
        # Una base gestionada por Alembic debe conservar las tablas del
        # baseline; si faltan, el historial no es coherente.
        missing = set(BASELINE_SCHEMA) - user_tables
        if missing:
            return Classification(
                DatabaseState.INCOMPATIBLE,
                "hay una versión de Alembic registrada pero faltan tablas "
                "del baseline",
                tuple(f"falta la tabla '{table}'" for table in sorted(missing)),
            )
        return Classification(
            DatabaseState.MANAGED,
            f"revisión registrada: {', '.join(revisions)}",
        )

    if not user_tables:
        return Classification(
            DatabaseState.EMPTY,
            "no hay tablas de la aplicación",
        )

    problems = _schema_differences(inspector, user_tables)
    if problems:
        return Classification(
            DatabaseState.INCOMPATIBLE,
            "el esquema existente no coincide exactamente con el baseline",
            tuple(problems),
        )

    return Classification(
        DatabaseState.ADOPTABLE,
        "el esquema coincide exactamente con el baseline y no tiene versión",
    )


def _run_alembic(*args: str, url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACK_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BootstrapError(
            f"alembic {' '.join(args)} falló:\n"
            f"{completed.stdout}{completed.stderr}"
        )


def bootstrap_database(url: str | None = None) -> Classification:
    """Clasifica la base y aplica la estrategia de migración adecuada."""
    database_url = url or Config.SQLALCHEMY_DATABASE_URI
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        classification = classify_database(engine)
    finally:
        engine.dispose()

    if classification.state is DatabaseState.INCOMPATIBLE:
        details = "\n".join(f"  - {detail}" for detail in classification.details)
        raise IncompatibleDatabaseError(
            f"{classification.reason}. No se modificó la base de datos.\n"
            f"{details}"
        )

    if classification.state is DatabaseState.ADOPTABLE:
        # Solo se marca el baseline después de verificar el esquema completo.
        _run_alembic("stamp", BASELINE_REVISION, url=database_url)

    _run_alembic("upgrade", "head", url=database_url)
    return classification


def main() -> int:
    try:
        classification = bootstrap_database()
    except BootstrapError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Base de datos: {classification.state.value} ({classification.reason})")
    print("Migraciones aplicadas hasta head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
