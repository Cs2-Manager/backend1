"""Utilidades de tiempo compartidas entre servicios.

Centraliza funciones de fecha/hora que se repetían en varios módulos.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Devuelve la hora actual en UTC con zona horaria."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Convierte un datetime a UTC, asumiendo UTC local si no tiene zona."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
