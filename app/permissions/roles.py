"""Roles internos de un equipo.

El rol competitivo del jugador (IGL, AWPer, etc.) vivirá en su perfil y es
independiente de estos permisos.
"""

from enum import Enum


class TeamRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    COACH = "COACH"
    PLAYER = "PLAYER"


TEAM_ROLE_VALUES = tuple(item.value for item in TeamRole)


def coerce_team_role(value):
    if isinstance(value, TeamRole):
        return value
    return TeamRole(str(value).strip().upper())
