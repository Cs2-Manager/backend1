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
)
from app.models.user import User
from app.permissions import (
    can_delete_team_lineup,
    can_manage_team_lineups,
    can_set_primary_team_lineup,
    can_view,
    coerce_team_role,
)
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
    return (
        selectinload(TeamLineup.players)
        .selectinload(TeamLineupPlayer.user)
        .selectinload(User.profile),
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
        ),
    }


def lineup_payload(lineup, viewer, role):
    return serialize_team_lineup(
        lineup,
        permissions=_lineup_permissions(viewer, role, lineup),
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
        status=status,
        is_primary=False,
        created_at=now,
        updated_at=now,
    )
    db.session.add(lineup)
    db.session.flush()
    _add_players(lineup, starters, substitutes, now)
    _commit_or_conflict("Lineup could not be created")
    return lineup


def update_lineup(user, team_id, lineup_id, data):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    values = _validated_values(data, partial=True)
    for field, value in values.items():
        setattr(lineup, field, value)
    lineup.updated_at = _utcnow()
    _commit_or_conflict("Lineup could not be updated")
    return lineup


def replace_players(user, team_id, lineup_id, data):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    starters, substitutes = _parse_roster(data, team)
    if lineup.status == "ACTIVE":
        _ensure_roster_can_be_active(starters)

    now = _utcnow()
    lineup.players = []
    db.session.flush()
    _add_players(lineup, starters, substitutes, now)
    lineup.updated_at = now
    _commit_or_conflict("Lineup players could not be updated")
    return lineup


def activate_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    _ensure_roster_can_be_active(_starters(lineup))
    _ensure_players_are_members(team, lineup)

    if lineup.status != "ACTIVE":
        lineup.status = "ACTIVE"
        lineup.updated_at = _utcnow()
        _commit_or_conflict("Lineup could not be activated")
    return lineup


def deactivate_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_manage(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    if lineup.status != "DRAFT" or lineup.is_primary:
        lineup.status = "DRAFT"
        lineup.is_primary = False
        lineup.updated_at = _utcnow()
        _commit_or_conflict("Lineup could not be deactivated")
    return lineup


def set_primary_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_primary(user, team)
    # Serializa la elección de principal por equipo en PostgreSQL.
    db.session.query(Team.id).filter(Team.id == team.id).with_for_update().first()
    lineup = _get_lineup(team.id, lineup_id, for_update=True)

    _ensure_can_be_primary(team, lineup)

    db.session.query(TeamLineup).filter(
        TeamLineup.team_id == team.id,
        TeamLineup.id != lineup.id,
    ).update(
        {TeamLineup.is_primary: False},
        synchronize_session=False,
    )
    lineup.is_primary = True
    lineup.updated_at = _utcnow()
    _commit_or_conflict("Another lineup is already primary")
    return lineup


def delete_lineup(user, team_id, lineup_id):
    team = _get_team(team_id)
    _require_delete(user, team)
    lineup = _get_lineup(team.id, lineup_id, for_update=True)
    db.session.delete(lineup)
    db.session.commit()


def detach_member(team_id, user_id):
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
