"""Construcción de eventos privados, actividad y destinatarios.

Reglas clave:

- Los destinatarios nunca llegan desde React: se calculan aquí consultando la
  base de datos y las reglas de permisos vigentes.
- Un administrador global no recibe eventos privados de equipos ajenos por el
  solo hecho de serlo.
- Si un destinatario dejó el equipo o el recurso ya no existe, el evento no se
  emite para esa persona.
- La outbox y las notificaciones se agregan a la MISMA transacción de negocio.
  La entrega HTTP ocurre después del commit y puede reintentarse.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models import Map, TeamMember
from app.models.realtime import TeamActivity
from app.models.team import Team
from app.notifications.outbox import dispatch_event, queue_event

logger = logging.getLogger(__name__)

MANAGER_ROLES = ("CAPTAIN", "COACH")
_MAX_USERNAME = 80
_MAX_TEAM_NAME = 80
_MAX_TEAM_TAG = 10
_MAX_MAP_NAME = 80
_MAX_LINEUP_TITLE = 160
_MAX_LINEUP_TYPE = 20
_MAX_DESCRIPTION = 500
_MAX_PATH = 300


def _isoformat(value):
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _clip(value, limit, fallback=""):
    text = str(value or "").strip()
    return text[:limit] if text else fallback


def _user_ref(user):
    if user is None:
        return None
    return {
        "user_id": user.id,
        "username": _clip(user.username, _MAX_USERNAME, "usuario"),
    }


def _team_ref(team):
    return {
        "id": team.id,
        "name": _clip(team.name, _MAX_TEAM_NAME, "Equipo"),
        "tag": _clip(team.tag, _MAX_TEAM_TAG) or None,
    }


def _map_ref(map_obj):
    if map_obj is None:
        return None
    return {
        "id": map_obj.id,
        "name": _clip(map_obj.name, _MAX_MAP_NAME, "Mapa"),
    }


def _snapshot_lineup_ref(proposal, fallback=None):
    snapshot = proposal.snapshot or {}
    return {
        "id": proposal.source_lineup_id or proposal.id,
        "title": _clip(
            snapshot.get("title"),
            _MAX_LINEUP_TITLE,
            _clip(getattr(fallback, "title", None), _MAX_LINEUP_TITLE, "Lineup"),
        ),
        "type": _clip(
            snapshot.get("type"),
            _MAX_LINEUP_TYPE,
            _clip(getattr(fallback, "type", None), _MAX_LINEUP_TYPE, "OTHER"),
        ),
    }


def _managers(team_id):
    rows = (
        db.session.query(TeamMember.user_id)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.role.in_(MANAGER_ROLES),
        )
        .all()
    )
    return {user_id for (user_id,) in rows if user_id}


def _is_member(team_id, user_id):
    if not user_id:
        return False
    return (
        db.session.query(TeamMember.id)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
        )
        .first()
        is not None
    )


def _members(team_id):
    rows = (
        db.session.query(TeamMember.user_id)
        .filter(TeamMember.team_id == team_id)
        .all()
    )
    return {user_id for (user_id,) in rows if user_id}


def _authorized_recipients(team_id, *, extras=(), exclude=()):
    """Managers actuales + extras que sigan siendo integrantes del equipo."""
    recipients = _managers(team_id)
    for user_id in extras:
        if user_id and _is_member(team_id, user_id):
            recipients.add(user_id)
    recipients.difference_update({user_id for user_id in exclude if user_id})
    return sorted(recipients)


def _envelope(
    event_type,
    *,
    occurred_at,
    resource_id,
    team,
    actor,
    recipients,
    payload,
):
    actor_ref = _user_ref(actor)
    if actor_ref is None:
        logger.warning("Realtime event %s skipped: missing actor", event_type)
        return None
    if not recipients:
        logger.info(
            "Realtime event %s skipped: no authorized recipients", event_type
        )
        return None
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": _isoformat(occurred_at),
        "version": 1,
        "resource_id": resource_id,
        "team_id": team.id,
        "actor": actor_ref,
        "recipients": sorted(set(recipients)),
        "payload": payload,
    }


def dispatch(event):
    """Intenta entregar un evento ya encolado. Se llama tras el commit."""
    if not event:
        return False
    return dispatch_event(event["event_id"])


# --- Invitaciones -----------------------------------------------------------


def build_invitation_created(invitation, team, invited_user, actor):
    if invited_user is None or actor is None or team is None:
        return None
    recipients = [invited_user.id] if invited_user.id != actor.id else []
    return _envelope(
        "team.invitation.created",
        occurred_at=invitation.created_at,
        resource_id=invitation.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload={
            "invitation_id": invitation.id,
            "team": _team_ref(team),
            "role": _clip(invitation.role, 10, "PLAYER"),
            "invited_by": _user_ref(actor),
        },
    )


def build_invitation_accepted(invitation, actor):
    team = invitation.team
    if team is None or actor is None:
        return None
    recipients = _authorized_recipients(
        team.id, extras=(invitation.invited_by_id,), exclude=(actor.id,)
    )
    return _envelope(
        "team.invitation.accepted",
        occurred_at=invitation.responded_at or invitation.created_at,
        resource_id=invitation.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload={
            "invitation_id": invitation.id,
            "team": _team_ref(team),
            "member": _user_ref(actor),
            "role": _clip(invitation.role, 10, "PLAYER"),
        },
    )


def build_invitation_rejected(invitation, actor):
    team = invitation.team
    if team is None or actor is None:
        return None
    recipients = _authorized_recipients(
        team.id, extras=(invitation.invited_by_id,), exclude=(actor.id,)
    )
    return _envelope(
        "team.invitation.rejected",
        occurred_at=invitation.responded_at or invitation.created_at,
        resource_id=invitation.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload={
            "invitation_id": invitation.id,
            "team": _team_ref(team),
            "user": _user_ref(actor),
        },
    )


# --- Propuestas de granadas -------------------------------------------------


def _proposal_context(proposal, actor):
    team = db.session.get(Team, proposal.team_id)
    map_obj = db.session.get(Map, proposal.map_id)
    if team is None or map_obj is None or actor is None:
        logger.warning(
            "Realtime proposal event skipped: missing team, map or actor"
        )
        return None
    return team, map_obj


def build_proposal_created(proposal, lineup, actor):
    context = _proposal_context(proposal, actor)
    if context is None:
        return None
    team, map_obj = context

    recipients = _authorized_recipients(team.id, exclude=(actor.id,))
    return _envelope(
        "grenade.proposal.created",
        occurred_at=proposal.created_at,
        resource_id=proposal.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload={
            "proposal_id": proposal.id,
            "team": _team_ref(team),
            "map": _map_ref(map_obj),
            "lineup": _snapshot_lineup_ref(proposal, fallback=lineup),
            "author": _user_ref(actor),
        },
    )


def _proposal_author_recipients(proposal, team, actor):
    """A decision only notifies its author if still a member, never the actor."""
    author_id = proposal.author_id
    return (
        [author_id]
        if author_id
        and author_id != actor.id
        and _is_member(team.id, author_id)
        else []
    )


def _build_proposal_decision(event_type, proposal, actor):
    context = _proposal_context(proposal, actor)
    if context is None:
        return None
    team, map_obj = context
    recipients = _proposal_author_recipients(proposal, team, actor)
    payload = {
        "proposal_id": proposal.id,
        "team": _team_ref(team),
        "map": _map_ref(map_obj),
        "lineup": _snapshot_lineup_ref(
            proposal, fallback=proposal.source_lineup
        ),
    }
    if event_type == "grenade.proposal.approved":
        payload["approved_lineup_id"] = proposal.approved_lineup_id

    return _envelope(
        event_type,
        occurred_at=proposal.decided_at or proposal.created_at,
        resource_id=proposal.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload=payload,
    )


def build_proposal_approved(proposal, actor):
    return _build_proposal_decision(
        "grenade.proposal.approved", proposal, actor
    )


def build_proposal_rejected(proposal, actor):
    return _build_proposal_decision(
        "grenade.proposal.rejected", proposal, actor
    )


# --- Actividad de equipo ----------------------------------------------------


def record_activity(
    team_id,
    actor,
    activity_type,
    description,
    *,
    resource_type,
    resource_id,
    path,
    metadata=None,
    exclude=(),
    occurred_at=None,
):
    """Agrega una fila de actividad y su evento de outbox a la transacción.

    Devuelve el evento para entregarlo después del commit. No lanza si faltan
    datos: la operación de negocio nunca se revierte por un fallo de actividad.
    """
    if actor is None:
        return None
    team = db.session.get(Team, team_id)
    if team is None:
        return None

    recipients = _members(team_id) - {user_id for user_id in exclude if user_id}
    if not recipients:
        return None

    now = occurred_at or datetime.now(timezone.utc)
    actor_ref = _user_ref(actor)
    activity = TeamActivity(
        event_id=str(uuid.uuid4()),
        team_id=team.id,
        activity_type=_clip(activity_type, 60, "team.updated"),
        description=_clip(description, _MAX_DESCRIPTION, "Actividad del equipo"),
        actor_id=actor.id,
        actor_username=actor_ref["username"],
        resource_type=_clip(resource_type, 40, "team"),
        resource_id=resource_id if isinstance(resource_id, int) else team.id,
        path=_clip(path, _MAX_PATH, f"/teams/{team.id}"),
        activity_metadata=metadata or None,
        created_at=now,
    )
    db.session.add(activity)
    db.session.flush()

    event = _envelope(
        "team.activity",
        occurred_at=now,
        resource_id=activity.id,
        team=team,
        actor=actor,
        recipients=recipients,
        payload={
            "activity_id": activity.id,
            "activity_type": activity.activity_type,
            "description": activity.description,
            "actor": actor_ref,
            "team": _team_ref(team),
            "resource_type": activity.resource_type,
            "resource_id": activity.resource_id,
            "path": activity.path,
            "created_at": _isoformat(now),
            "metadata": metadata or {},
        },
    )
    queue_event(event)
    return event


# --- Compatibilidad: publicación inmediata ----------------------------------
# Los servicios usan build_* + queue_event antes del commit. Estas funciones se
# conservan para integraciones externas y pruebas que publican después del
# commit; crean una transacción de outbox propia.


def _publish(event):
    if not event:
        return False
    queue_event(event)
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.warning("Realtime event could not be queued")
        return False
    return dispatch(event)


def publish_invitation_created(invitation, team, invited_user, actor):
    return _publish(
        build_invitation_created(invitation, team, invited_user, actor)
    )


def publish_invitation_accepted(invitation, actor):
    return _publish(build_invitation_accepted(invitation, actor))


def publish_invitation_rejected(invitation, actor):
    return _publish(build_invitation_rejected(invitation, actor))


def publish_proposal_created(proposal, lineup, actor):
    return _publish(build_proposal_created(proposal, lineup, actor))


def publish_proposal_approved(proposal, actor):
    return _publish(build_proposal_approved(proposal, actor))


def publish_proposal_rejected(proposal, actor):
    return _publish(build_proposal_rejected(proposal, actor))
