"""Servicio de matches.

Proporciona funciones para gestionar partidas de jugadores."""

from app.extensions import db
from app.models import Match


def record_match(profile, data):
    """Registra una partida real para un perfil."""
    from app.models import Player

    match = Match(
        profile_id=profile.get("id") if profile else None,
        opponent=data.get("opponent", ""),
        score=data.get("score", 0),
        map_name=data.get("map_name", ""),
        duration=data.get("duration"),
        date=data.get("date"),
        notes=data.get("notes"),
    )
    db.session.add(match)
    db.session.commit()
    return match


def matches_query(profile):
    """Retorna matches para un perfil."""


from app.models import Match
from app.extensions import db
from sqlalchemy import select

stmt = select(Match).where(Match.profile_id == (profile.get("id") if profile else 0))
return db.session.execute(stmt).scalars().all()
