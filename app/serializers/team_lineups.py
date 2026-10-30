"""Serializadores de las alineaciones competitivas de un equipo.

El serializador solo expone datos públicos de los usuarios (los mismos que
`serialize_team_user`): nunca email, hash de contraseña ni privilegios
administrativos.
"""

from app.models.team_lineup import (
    TEAM_LINEUP_MAX_SUBSTITUTES,
    TEAM_LINEUP_ROLES,
    TEAM_LINEUP_STARTERS,
)
from app.serializers.teams import serialize_team_user

ROLE_ORDER = {role: index for index, role in enumerate(TEAM_LINEUP_ROLES)}


def _iso(value):
    return value.isoformat() if value is not None else None


def serialize_team_lineup_player(entry):
    return {
        "id": entry.id,
        "role": entry.role,
        "is_starter": bool(entry.is_starter),
        "user": serialize_team_user(entry.user),
    }


def _sorted_players(lineup):
    return sorted(
        lineup.players,
        key=lambda entry: (
            not entry.is_starter,
            ROLE_ORDER.get(entry.role, len(TEAM_LINEUP_ROLES)),
            entry.id,
        ),
    )


def serialize_team_lineup(lineup, *, permissions=None, is_complete=None):
    """Representación completa de una lineup para listado y detalle."""
    players = _sorted_players(lineup)
    starters = [entry for entry in players if entry.is_starter]
    substitutes = [entry for entry in players if not entry.is_starter]
    complete = len(starters) == TEAM_LINEUP_STARTERS

    return {
        "id": lineup.id,
        "team_id": lineup.team_id,
        "name": lineup.name,
        "description": lineup.description,
        "status": lineup.status,
        "is_primary": bool(lineup.is_primary),
        "created_at": _iso(lineup.created_at),
        "updated_at": _iso(lineup.updated_at),
        "starters": [
            serialize_team_lineup_player(entry) for entry in starters
        ],
        "substitutes": [
            serialize_team_lineup_player(entry) for entry in substitutes
        ],
        "starters_count": len(starters),
        "substitutes_count": len(substitutes),
        "is_complete": complete if is_complete is None else bool(is_complete),
        "limits": {
            "starters": TEAM_LINEUP_STARTERS,
            "substitutes": TEAM_LINEUP_MAX_SUBSTITUTES,
        },
        "permissions": permissions or {},
    }
