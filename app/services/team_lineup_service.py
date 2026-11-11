"""Lógica de negocio de las alineaciones competitivas de un equipo.

La autorización se delega en `app.permissions`; las restricciones críticas
también existen en la base de datos:

- `team_lineup_players` es único por lineup/usuario.
- Solo una lineup principal por equipo (índice único parcial).
- Estados y roles de juego limitados por `CHECK`.

Las operaciones de reemplazo de roster, activación y elección de principal
bloquean la fila correspondiente para serializar escrituras concurrentes en
PostgreSQL. En SQLite el bloqueo no aplica, pero las restricciones de la base
siguen impidiendo estados inválidos.
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import ApiError
from app.extensions import db
from app.models.team import Team, TeamMember
from app.models.team_lineup import (
    TEAM_LINEUP_MAX_SUBSTITUTES,
    TEAM_LINEUP_ROLES,
    TEAM_LINEUP_STARTERS,
    TEAM_LINEUP_STATUSES,
    TeamLineup,
    TeamLineupPlayer,
    TeamLineupHistory,
)
from app.models.user import User
from app.permissions import (
    can_delete_team_lineup,
    can_manage_team_lineups,
    can_set_primary_team_lineup,
    can_view,
    coerce_team_role,
)
from app.notifications.outbox import dispatch_event
from app.realtime.events import record_activity
from app.serializers import serialize_team_lineup
from app.validators import clean_str

LINEUP_NAME_MIN = 2
LINEUP_NAME_MAX = 80
LINEUP_DESCRIPTION_MAX = 1000
LIMITS = {
    "starters": TEAM_LINEUP_STARTERS,
    "substitutes": TEAM_LINEUP_MAX_SUBSTITUTES,
}


def _utcnow():
    return datetime.now(timezone.utc)


def _team_options():
    return (
        selectinload(Team.members)
        .selectinload(TeamMember.user)
        .selectinload(User.profile),
    )


def _lineup_options():
    from app.models.player_profile import PlayerProfile
    return (
        selectinload(TeamLineup.map),
        selectinload(TeamLineup.players)
        .selectinload(TeamLineupPlayer.user)
        .selectinload(User.profile),
        selectinload(TeamLineup.players).selectinload(TeamLineupPlayer.user).selectinload(User.profile).selectinload(PlayerProfile.competitive),
    )


def _get_team(team_id):
    team = (
        db.session.query(Team)
        .options(*_team_options())
        .filter(Team.id == team_id)
        .first()
    )
    if team is None:
        raise ApiError("Team not found", status_code=404)
    return team


def _role_for(user, team):
    if user is None:
        return None
    membership = (
        db.session.query(TeamMember)
        .filter(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        return None
    return coerce_team_role(membership.role)


def _ensure_visible(viewer, team):
    role = _role_for(viewer, team)
    if not can_view(
        viewer,
        team.visibility,
        is_team_member=role is not None,
    ):
        raise ApiError("Team is private", status_code=403)
    return role


def _require_manage(user, team):
    role = _ensure_visible(user, team)
    if not can_manage_team_lineups(user, role):
        raise ApiError("You cannot manage this team's lineups", status_code=403)
    return role


def _require_delete(user, team):
    role = _ensure_visible(user, team)
    if not can_delete_team_lineup(user, role):
        raise ApiError("You cannot delete this team's lineups", status_code=403)
    return role


def _require_primary(user, team):
    role = _ensure_visible(user, team)
    if not can_set_primary_team_lineup(user, role):
        raise ApiError(
            "You cannot choose the primary lineup", status_code=403
        )
    return role


def _get_lineup(team_id, lineup_id, *, for_update=False):
    query = (
        db.session.query(TeamLineup)
        .options(*_lineup_options())
        .filter(
            TeamLineup.id == lineup_id,
            TeamLineup.team_id == team_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    lineup = query.first()
    if lineup is None:
        raise ApiError("Lineup not found", status_code=404)
    return lineup


def _starters(lineup):
    return [entry for entry in lineup.players if entry.is_starter]


def _is_complete(lineup):
    return len(_starters(lineup)) == TEAM_LINEUP_STARTERS


def _lineup_permissions(viewer, role, lineup):
    manage = can_manage_team_lineups(viewer, role)
    complete = _is_complete(lineup)
    return {
        "can_view": True,
        "can_edit": manage,
        "can_manage_players": manage,
        "can_delete": can_delete_team_lineup(viewer, role),
        "can_activate": manage and lineup.status == "DRAFT" and complete,
        "can_deactivate": manage and lineup.status == "ACTIVE",
        "can_set_primary": (
            can_set_primary_team_lineup(viewer, role)
            and lineup.status == "ACTIVE"
            and complete
            and lineup.map_id is None
        ),
    }


def lineup_payload(lineup, viewer, role):
    return serialize_team_lineup(
        lineup,
        permissions=_lineup_permissions(viewer, role, lineup),
        viewer=viewer,
    )


def list_lineups(viewer, team_id):
    team = _get_team(team_id)
    role = _ensure_visible(viewer, team)
    lineups = (
        db.session.query(TeamLineup)
        .options(*_lineup_options())
        .filter(TeamLineup.team_id == team.id)
        .order_by(
            TeamLineup.is_primary.desc(),
            TeamLineup.created_at,
            TeamLineup.id,
        )
        .all()
    )
    return team, lineups, role


def get_lineup(viewer, team_id, lineup_id):
    team = _get_team(team_id)
    role = _ensure_visible(viewer, team)
    lineup = _get_lineup(team.id, lineup_id)
    return team, lineup, role


def _validate_name(value, errors):
    name = clean_str(value)
    if not name:
        errors["name"] = "name is required"
        return None
    if len(name) < LINEUP_NAME_MIN:
        errors["name"] = (
            f"name must be at least {LINEUP_NAME_MIN} characters"
        )
        return None
    if len(name) > LINEUP_NAME_MAX:
        errors["name"] = f"name must be at most {LINEUP_NAME_MAX} characters"
        return None
    if any(ord(char) < 32 for char in name):
        errors["name"] = "name contains invalid characters"
        return None
    return name


def _validated_values(data, *, partial):
    errors = {}
    values = {}
    if "map_id" in data:
        from app.models.map import Map
        mid = data["map_id"]
        if mid is not None and (type(mid) is not int or db.session.get(Map, mid) is None):
            errors["map_id"] = "Map not found"
        else:
            values["map_id"] = mid
    if "notes" in data:
        if not isinstance(data["notes"], str) or len(data["notes"]) > 4000:
            errors["notes"] = "notes must be text up to 4000 characters"
        else:
            values["notes"] = data["notes"].strip()

    if not partial or "name" in data:
        values["name"] = _validate_name(data.get("name"), errors)
    if "description" in data:
        description = clean_str(data.get("description"))
        if len(description) > LINEUP_DESCRIPTION_MAX:
            errors["description"] = (
                "description must be at most "
                f"{LINEUP_DESCRIPTION_MAX} characters"
            )
        else:
            values["description"] = description or None

    if errors:
        raise ApiError("Invalid lineup", status_code=400, fields=errors)
    return values


def _validate_status(value):
    status = clean_str(value).upper() or "DRAFT"
    if status not in TEAM_LINEUP_STATUSES:
        raise ApiError(
            "Invalid lineup status",
            status_code=400,
            fields={
                "status": (
                    "status must be one of "
                    f"{', '.join(TEAM_LINEUP_STATUSES)}"
                )
            },
        )
    return status


def _coerce_user_id(value):
    if isinstance(value, bool):
        raise ValueError
    return int(value)


def _parse_entries(raw, field, member_ids, errors):
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        errors[field] = f"{field} must be a list"
        return []

    entries = []
    for item in raw:
        if not isinstance(item, dict):
            errors[field] = f"{field} must contain player objects"
            continue
        try:
            user_id = _coerce_user_id(item.get("user_id"))
        except (TypeError, ValueError):
            errors[field] = f"{field} contains an invalid user_id"
            continue
        if user_id not in member_ids:
            errors[field] = (
                f"{field} contains a user who is not a member of the team"
            )
            continue

        role = clean_str(item.get("role")).upper() or None
        if role is not None and role not in TEAM_LINEUP_ROLES:
            errors[field] = (
                "game role must be one of "
                f"{', '.join(TEAM_LINEUP_ROLES)}"
            )
            continue
        entries.append({"user_id": user_id, "role": role})
    return entries


def _parse_roster(data, team):
    errors = {}
    member_ids = {member.user_id for member in team.members}
    starters = _parse_entries(data.get("starters"), "starters", member_ids, errors)
    substitutes = _parse_entries(
        data.get("substitutes"), "substitutes", member_ids, errors
    )

    if len(starters) > TEAM_LINEUP_STARTERS:
        errors["starters"] = (
            f"starters must have at most {TEAM_LINEUP_STARTERS} players"
        )
    if len(substitutes) > TEAM_LINEUP_MAX_SUBSTITUTES:
        errors["substitutes"] = (
            "substitutes must have at most "
            f"{TEAM_LINEUP_MAX_SUBSTITUTES} players"
        )

    user_ids = [entry["user_id"] for entry in starters + substitutes]
    if len(user_ids) != len(set(user_ids)):
        errors["starters"] = (
            "A player cannot be a starter and a substitute, or appear twice"
        )

    if errors:
        raise ApiError("Invalid lineup roster", status_code=400, fields=errors)
    return starters, substitutes


def _ensure_roster_can_be_active(starters):
    if len(starters) != TEAM_LINEUP_STARTERS:
        raise ApiError(
            "An active lineup must have exactly 5 starters",
            status_code=400,
            fields={
                "starters": "An active lineup must have exactly 5 starters"
            },
        )


def _ensure_players_are_members(team, lineup):
    member_ids = {member.user_id for member in team.members}
    starters = [entry for entry in lineup.players if entry.is_starter]
    substitutes = [entry for entry in lineup.players if not entry.is_starter]
    fields = {}

    if any(entry.user_id not in member_ids for entry in starters):
        fields["starters"] = "Every starter must currently belong to the team"
    if any(entry.user_id not in member_ids for entry in substitutes):
        fields["substitutes"] = (
            "Every substitute must currently belong to the team"
        )
    if fields:
        raise ApiError(
            "Lineups cannot contain players who left the team",
            status_code=409,
            fields=fields,
        )


def _ensure_can_be_primary(team, lineup):
    if lineup.map_id is not None:
        raise ApiError("The primary lineup must be general", status_code=400)
    if lineup.status != "ACTIVE" or not _is_complete(lineup):
        raise ApiError(
            "Only a complete active lineup can be primary",
            status_code=400,
            fields={
                "lineup": (
                    "The lineup must be ACTIVE and have exactly 5 starters"
                )
            },
        )
    _ensure_players_are_members(team, lineup)


def _commit_or_conflict(message):
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ApiError(message, status_code=409) from error


def _dispatch(event):
    """Entrega best-effort después del commit; nunca revierte la operación."""
    if event:
        dispatch_event(event["event_id"])


def _lineup_activity(user, team, lineup, activity_type, description):
    return record_activity(
        team.id,
        user,
        activity_type,
        description,
        resource_type="team_lineup",
        resource_id=lineup.id,
        path=f"/teams/{team.id}/lineups/{lineup.id}",
        metadata={"lineup_id": lineup.id, "lineup_name": lineup.name},
    )


def _add_players(lineup, starters, substitutes, now):
    for entry in starters:
        lineup.players.append(
            TeamLineupPlayer(
                user_id=entry["user_id"],
                role=entry["role"],
                is_starter=True,
                created_at=now,
            )
        )
    for entry in substitutes:
        lineup.players.append(
            TeamLineupPlayer(
                user_id=entry["user_id"],
                role=entry["role"],
                is_starter=False,
                created_at=now,
            )
        )


def create_lineup(user, team_id, data):
    team = _get_team(team_id)
    _require_manage(user, team)

    values = _validated_values(data, partial=False)
    status = _validate_status(data.get("status"))
    starters, substitutes = _parse_roster(data, team)
    if status == "ACTIVE":
        _ensure_roster_can_be_active(starters)

    now = _utcnow()
    lineup = TeamLineup(
        team_id=team.id,
        name=values["name"],
        description=values.get("description"),
        map_id=values.get("map_id"),
        notes=values.get("notes", ""),
        status=status,
        is_primary=False,
        created_at=now,
        updated_at=now,
    )
    db.session.add(lineup)
    db.session.flush()
    _add_players(lineup, starters, substitutes, now)
    _audit(lineup, user, "CREATED", None)
    activity = _lineup_activity(
        user,
        team,
        lineup,
        "team_lineup.created",
        f'{user.username} creó la lineup "{lineup.name}".',
    )
    _commit_or_conflict("Lineup could not be created")
    _dispatch(activity)
    return lineup


def update_lineup(user, team_id, lineup_id, data):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    values = _validated_values(data, partial=True)
    before = _snapshot(lineup)
    if lineup.is_primary and values.get("map_id") is not None:
        raise ApiError("The primary lineup must remain general", status_code=400)
    if values.get('map_id') is not None and values['map_id'] != lineup.map_id:
        from app.models.lineup_recommendation import LineupRecommendation
        from app.models.tactics import TeamStrategy
        mismatch = db.session.query(LineupRecommendation).join(TeamStrategy, TeamStrategy.id == LineupRecommendation.strategy_id).filter(LineupRecommendation.lineup_id == lineup.id, TeamStrategy.map_id != values['map_id']).first()
        if mismatch:
            raise ApiError('Remove recommendations from other maps before changing the map', status_code=400)
    for field, value in values.items():
        setattr(lineup, field, value)
    lineup.updated_at = _utcnow()
    _audit(lineup, user, "UPDATED", before)
    activity = _lineup_activity(
        user,
        team,
        lineup,
        "team_lineup.updated",
        f'{user.username} actualizó la lineup "{lineup.name}".',
    )
    _commit_or_conflict("Lineup could not be updated")
    _dispatch(activity)
    return lineup


def replace_players(user, team_id, lineup_id, data):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    starters, substitutes = _parse_roster(data, team)
    if lineup.status == "ACTIVE":
        _ensure_roster_can_be_active(starters)

    now = _utcnow()
    before = _snapshot(lineup)
    lineup.players = []
    db.session.flush()
    _add_players(lineup, starters, substitutes, now)
    lineup.updated_at = now
    _audit(lineup, user, "ROSTER_UPDATED", before)
    activity = _lineup_activity(
        user,
        team,
        lineup,
        "team_lineup.roster_updated",
        f'{user.username} modificó el roster de "{lineup.name}".',
    )
    _commit_or_conflict("Lineup players could not be updated")
    _dispatch(activity)
    return lineup


def activate_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    _ensure_roster_can_be_active(_starters(lineup))
    _ensure_players_are_members(team, lineup)

    if lineup.status != "ACTIVE":
        before = _snapshot(lineup)
        lineup.status = "ACTIVE"
        lineup.updated_at = _utcnow()
        _audit(lineup, user, "ACTIVATED", before)
        activity = _lineup_activity(
            user,
            team,
            lineup,
            "team_lineup.activated",
            f'{user.username} activó la lineup "{lineup.name}".',
        )
        _commit_or_conflict("Lineup could not be activated")
        _dispatch(activity)
    return lineup


def deactivate_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    if lineup.status != "DRAFT" or lineup.is_primary:
        before = _snapshot(lineup)
        lineup.status = "DRAFT"
        lineup.is_primary = False
        lineup.updated_at = _utcnow()
        _audit(lineup, user, "DEACTIVATED", before)
        activity = _lineup_activity(
            user,
            team,
            lineup,
            "team_lineup.deactivated",
            f'{user.username} desactivó la lineup "{lineup.name}".',
        )
        _commit_or_conflict("Lineup could not be deactivated")
        _dispatch(activity)
    return lineup


def set_primary_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_primary(user, team)
    # Serializa la elección de principal por equipo en PostgreSQL.
    db.session.query(Team.id).filter(Team.id == team.id).with_for_update().first()
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    _ensure_can_be_primary(team, lineup)

    previous = db.session.query(TeamLineup).filter(
        TeamLineup.team_id == team.id,
        TeamLineup.id != lineup.id,
        TeamLineup.is_primary.is_(True),
    ).all()
    for item in previous:
        before = _snapshot(item)
        item.is_primary = False
        _audit(item, user, "PRIMARY_REMOVED", before)
    db.session.flush()
    before = _snapshot(lineup)
    lineup.is_primary = True
    lineup.updated_at = _utcnow()
    _audit(lineup, user, "PRIMARY_SELECTED", before)
    activity = _lineup_activity(
        user,
        team,
        lineup,
        "team_lineup.primary_selected",
        f'{user.username} eligió "{lineup.name}" como lineup principal.',
    )
    _commit_or_conflict("Another lineup is already primary")
    _dispatch(activity)
    return lineup


def delete_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_delete(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)
    _audit(lineup, user, "DELETED", _snapshot(lineup), deleted=True)
    from app.models.lineup_recommendation import LineupRecommendation
    db.session.query(LineupRecommendation).filter_by(lineup_id=lineup_id).delete()
    from app.models.tactics import TeamStrategy, TeamMapSetup, StrategyRevision
    from app.serializers.tactics import strategy_payload
    for strategy in db.session.query(TeamStrategy).filter_by(lineup_id=lineup_id):
        db.session.add(StrategyRevision(strategy_id=strategy.id, version=strategy.version, author_id=user.id, snapshot=strategy_payload(strategy)))
        strategy.lineup_id = None
    for setup in db.session.query(TeamMapSetup).filter_by(lineup_id=lineup_id):
        setup.lineup_id = None
    activity = _lineup_activity(
        user,
        team,
        lineup,
        "team_lineup.deleted",
        f'{user.username} eliminó la lineup "{lineup.name}".',
    )
    db.session.delete(lineup)
    db.session.commit()
    _dispatch(activity)


def detach_member(team_id, user_id, actor=None):
    """Quita a un integrante de todas las lineups del equipo.

    No elimina las lineups ni los registros de otros jugadores. Si una lineup
    `ACTIVE` deja de tener cinco titulares, pasa a `DRAFT` y pierde el
    indicador de principal. La transacción la confirma quien invoca.
    """
    lineups = (
        db.session.query(TeamLineup)
        .filter(TeamLineup.team_id == team_id)
        .with_for_update()
        .all()
    )
    if not lineups:
        return

    lineup_ids = [lineup.id for lineup in lineups]
    entries = (
        db.session.query(TeamLineupPlayer)
        .filter(
            TeamLineupPlayer.lineup_id.in_(lineup_ids),
            TeamLineupPlayer.user_id == user_id,
        )
        .all()
    )
    if not entries:
        return

    affected = {entry.lineup_id for entry in entries}
    snapshots = {item.id: _snapshot(item) for item in lineups if item.id in affected}
    for entry in entries:
        db.session.delete(entry)
    db.session.flush()

    now = _utcnow()
    for lineup in lineups:
        if lineup.status != "ACTIVE":
            continue
        remaining = (
            db.session.query(func.count(TeamLineupPlayer.id))
            .filter(
                TeamLineupPlayer.lineup_id == lineup.id,
                TeamLineupPlayer.is_starter.is_(True),
            )
            .scalar()
        )
        if remaining < TEAM_LINEUP_STARTERS:
            lineup.status = "DRAFT"
            lineup.is_primary = False
            lineup.updated_at = now
    for lineup in lineups:
        if lineup.id in affected:
            db.session.expire(lineup, ["players"])
            lineup.updated_at = now
            _audit(lineup, actor, "MEMBER_DEPARTED", snapshots[lineup.id])


def _snapshot(lineup):
    return {"name": lineup.name, "description": lineup.description,
            "map_id": lineup.map_id, "notes": lineup.notes,
            "status": lineup.status, "is_primary": lineup.is_primary,
            "players": [{"user_id": p.user_id, "role": p.role, "is_starter": p.is_starter}
                        for p in lineup.players]}


def recommendations(user, team_id, lineup_id, data=None):
    from app.models.lineup_recommendation import LineupRecommendation
    from app.models.tactics import TeamStrategy
    from app.services.tactical_service import access
    access(user, team_id, data is not None)
    lineup = _get_lineup(team_id, lineup_id, for_update=data is not None)
    query = db.session.query(LineupRecommendation).filter_by(lineup_id=lineup_id)
    if data is not None:
        ids = data.get('strategy_ids')
        if not isinstance(ids, list) or len(ids) > 50 or any(type(i) is not int for i in ids) or len(ids) != len(set(ids)):
            raise ApiError('Invalid strategy identifiers', status_code=400)
        strategies = db.session.query(TeamStrategy).filter(TeamStrategy.id.in_(ids), TeamStrategy.team_id == team_id).all()
        if len(strategies) != len(ids) or any(lineup.map_id and s.map_id != lineup.map_id for s in strategies):
            raise ApiError('Recommended strategies must belong to this team and map', status_code=400)
        before = _snapshot(lineup)
        before['recommended_strategy_ids'] = [r.strategy_id for r in query]
        query.delete()
        db.session.add_all([LineupRecommendation(lineup_id=lineup_id, strategy_id=i) for i in ids])
        after = _snapshot(lineup)
        after['recommended_strategy_ids'] = ids
        db.session.add(TeamLineupHistory(team_id=team_id, lineup_id=lineup_id, actor_id=user.id, action='RECOMMENDATIONS_UPDATED', before=before, after=after))
        lineup.updated_at = _utcnow()
        _commit_or_conflict('Recommendations changed concurrently')
    return [r.strategy_id for r in query]


def _audit(lineup, actor, action, before, *, deleted=False):
    db.session.add(TeamLineupHistory(team_id=lineup.team_id, lineup_id=lineup.id,
        actor_id=actor.id if actor else None, action=action, before=before,
        after=None if deleted else _snapshot(lineup)))


def history(viewer, team_id, lineup_id=None):
    team = _get_team(team_id)
    _ensure_visible(viewer, team)
    query = db.session.query(TeamLineupHistory).filter_by(team_id=team_id)
    if lineup_id is not None:
        query = query.filter_by(lineup_id=lineup_id)
    return [{"id": h.id, "lineup_id": h.lineup_id, "actor_id": h.actor_id,
             "action": h.action, "before": h.before, "after": h.after,
             "created_at": h.created_at.isoformat()}
            for h in query.order_by(TeamLineupHistory.id.desc()).limit(200)]


def compare(viewer, team_id, first_id, second_id):
    _, first, role = get_lineup(viewer, team_id, first_id)
    second = _get_lineup(team_id, second_id)
    left = {p.user_id: (p.role, p.is_starter) for p in first.players}
    right = {p.user_id: (p.role, p.is_starter) for p in second.players}
    first_data, second_data = lineup_payload(first, viewer, role), lineup_payload(second, viewer, role)
    def average(data):
        values = [p['competitive']['elo'] for p in data['starters'] if p.get('competitive') and p['competitive']['elo'] is not None]
        return {'value': round(sum(values) / len(values), 1) if values else None, 'sample': len(values), 'source': 'PROFILE_RECORDED'}
    return {"first": first_data,
            "second": second_data,
            "added": sorted(right.keys() - left.keys()),
            "removed": sorted(left.keys() - right.keys()),
            "changed": sorted(uid for uid in left.keys() & right.keys() if left[uid] != right[uid]),
            "average_elo": {'first': average(first_data), 'second': average(second_data)},
            "statistics_note": "No verified collective statistics available"}
