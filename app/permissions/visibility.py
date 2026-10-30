"""Niveles de visibilidad compartidos por los recursos de la plataforma."""

from enum import Enum


class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"


VISIBILITY_VALUES = tuple(item.value for item in Visibility)


def coerce_visibility(value, default=Visibility.PRIVATE):
    """Convierte un valor de entrada a `Visibility` y valida el nivel."""
    if value is None or value == "":
        return default
    if isinstance(value, Visibility):
        return value
    try:
        return Visibility(str(value).strip().upper())
    except ValueError as error:
        raise ValueError(
            f"visibility must be one of {', '.join(VISIBILITY_VALUES)}"
        ) from error


def is_valid_visibility(value):
    try:
        coerce_visibility(value)
    except ValueError:
        return False
    return True
