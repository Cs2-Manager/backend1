"""Historial de actividad de equipos.

La actividad es privada: solo los integrantes **actuales** del equipo pueden
consultarla. NestJS entrega la misma actividad en vivo por la room `team:<id>`;
este módulo es la fuente persistente para el historial paginado.

No se expone actividad de un equipo a administradores globales ni a usuarios
que abandonaron el equipo, aunque conozcan su `team_id`.
"""

from datetime import datetime, timezone

from app.errors import ApiError
from app.extensions import db
from app.models.realtime import TeamActivity
from app.models.team import Team, TeamMember


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _ensure_member(user, team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        raise ApiError("Team not found", status_code=404)
    membership = (
        db.session.query(TeamMember.id)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        # Mismo mensaje que el resto de recursos privados: no se revela si el
        # equipo existe ni cuánta actividad tiene.
        raise ApiError("Team is private", status_code=403)
    return team


def list_for_team(user, team_id):
    """Consulta paginable del historial, ordenada de más reciente a más antiguo."""
    _ensure_member(user, team_id)
    return (
        db.session.query(TeamActivity)
        .filter(TeamActivity.team_id == team_id)
        .order_by(TeamActivity.created_at.desc(), TeamActivity.id.desc())
    )


def serialize_activity(activity):
    return {
        "id": activity.id,
        "event_id": activity.event_id,
        "team_id": activity.team_id,
        "activity_type": activity.activity_type,
        "description": activity.description,
        "actor": {
            "user_id": activity.actor_id,
            "username": activity.actor_username,
        },
        "resource_type": activity.resource_type,
        "resource_id": activity.resource_id,
        "path": activity.path,
        "metadata": activity.activity_metadata or {},
        "created_at": _iso(activity.created_at),
    }
