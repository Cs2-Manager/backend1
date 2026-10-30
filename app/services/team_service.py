"""Lógica de negocio de equipos, integrantes e invitaciones.

Todas las reglas de autorización se delegan en `app.permissions` y las
restricciones críticas también existen en la base de datos:

- `team_members.user_id` único (un equipo activo por usuario).
- Un solo capitán por equipo (índice único parcial).
- Una sola invitación pendiente por equipo/usuario (índice único parcial).

Las operaciones de aceptación bloquean la fila del usuario para serializar
aceptaciones simultáneas en PostgreSQL. En SQLite el bloqueo no aplica, pero la
restricción única sigue impidiendo dos pertenencias.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import ApiError
from app.extensions import db
from app.models.team import (
    INVITATION_STATUSES,
    Team,
    TeamInvitation,
    TeamMember,
)
from app.models.user import User
from app.permissions import (
    TeamRole,
    can_cancel_invitation,
    can_change_team_roles,
    can_delete_team_lineup,
    can_edit_team,
    can_manage_invitations,
    can_manage_team_lineups,
    can_remove_team_member,
    can_set_primary_team_lineup,
    can_transfer_captain,
    can_view,
    can_view_team_invitations,
    can_view_team_lineups,
    coerce_team_role,
    coerce_visibility,
)
from app.serializers import (
    serialize_team,
    serialize_team_member,
)
from app.services import team_lineup_service
from app.validators import clean_str, parse_url

TEAM_NAME_MIN = 2
TEAM_NAME_MAX = 80
TEAM_TAG_REGEX = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,9}$")
COUNTRY_REGEX = re.compile(r"^[A-Z]{2}$")
DESCRIPTION_MAX = 1000
INVITABLE_ROLES = ("COACH", "PLAYER")
ASSIGNABLE_ROLES = ("COACH", "PLAYER")
ROLE_ORDER = {"CAPTAIN": 0, "COACH": 1, "PLAYER": 2}


def _utcnow():
    return datetime.now(timezone.utc)


def _team_options():
    return (
        selectinload(Team.members)
        .selectinload(TeamMember.user)
        .selectinload(User.profile),
        selectinload(Team.created_by).selectinload(User.profile),
    )


def _invitation_options():
    return (
        selectinload(TeamInvitation.user).selectinload(User.profile),
        selectinload(TeamInvitation.invited_by).selectinload(User.profile),
        selectinload(TeamInvitation.team)
        .selectinload(Team.members)
        .selectinload(TeamMember.user)
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


def _get_membership(user_id, team_id=None, *, for_update=False):
    query = db.session.query(TeamMember).filter(TeamMember.user_id == user_id)
    if team_id is not None:
        query = query.filter(TeamMember.team_id == team_id)
    if for_update:
        query = query.with_for_update()
    return query.first()


def _role_for(user, team):
    if user is None:
        return None
    membership = _get_membership(user.id, team.id)
    if membership is None:
        return None
    return coerce_team_role(membership.role)


def _sorted_members(team):
    return sorted(
        team.members,
        key=lambda member: (
            ROLE_ORDER.get(member.role, 3),
            member.joined_at or member.id,
        ),
    )


def _team_permissions(viewer, role, is_member):
    return {
        "can_edit": can_edit_team(viewer, role),
        "can_manage_members": can_remove_team_member(viewer, role),
        "can_change_roles": can_change_team_roles(viewer, role),
        "can_manage_invitations": can_manage_invitations(viewer, role),
        "can_invite": can_manage_invitations(viewer, role),
        "can_transfer_captain": can_transfer_captain(viewer, role),
        "can_leave": bool(is_member),
        "can_view_lineups": can_view_team_lineups(viewer, role),
        "can_manage_lineups": can_manage_team_lineups(viewer, role),
        "can_delete_lineups": can_delete_team_lineup(viewer, role),
        "can_set_primary_lineup": can_set_primary_team_lineup(viewer, role),
    }


def _pending_invitations(team_id):
    return (
        db.session.query(TeamInvitation)
        .options(*_invitation_options())
        .filter(
            TeamInvitation.team_id == team_id,
            TeamInvitation.status == "PENDING",
        )
        .order_by(TeamInvitation.created_at.desc(), TeamInvitation.id.desc())
        .all()
    )


def _cancel_pending_invitations_for_user(user_id, now, *, exclude_id=None):
    query = db.session.query(TeamInvitation).filter(
        TeamInvitation.user_id == user_id,
        TeamInvitation.status == "PENDING",
    )
    if exclude_id is not None:
        query = query.filter(TeamInvitation.id != exclude_id)
    for invitation in query.all():
        invitation.status = "CANCELLED"
        invitation.responded_at = now


def _validate_name(value, errors):
    name = clean_str(value)
    if not name:
        errors["name"] = "name is required"
        return None
    if len(name) < TEAM_NAME_MIN:
        errors["name"] = f"name must be at least {TEAM_NAME_MIN} characters"
        return None
    if len(name) > TEAM_NAME_MAX:
        errors["name"] = f"name must be at most {TEAM_NAME_MAX} characters"
        return None
    if any(ord(char) < 32 for char in name):
        errors["name"] = "name contains invalid characters"
        return None
    return name


def _validate_tag(value, errors, *, team=None):
    tag = clean_str(value).upper()
    if not tag:
        return None
    if not TEAM_TAG_REGEX.match(tag):
        errors["tag"] = (
            "tag must be 2-10 characters using letters, numbers, - or _"
        )
        return None

    duplicate = db.session.query(Team.id).filter(Team.tag == tag)
    if team is not None:
        duplicate = duplicate.filter(Team.id != team.id)
    if duplicate.first():
        errors["tag"] = "tag is already in use"
        return None
    return tag


def _validate_optional_text(value, field, errors, max_length):
    text = clean_str(value)
    if not text:
        return None
    if len(text) > max_length:
        errors[field] = f"{field} must be at most {max_length} characters"
        return None
    return text


def _validate_country(value, errors):
    country = clean_str(value).upper()
    if not country:
        return None
    if not COUNTRY_REGEX.match(country):
        errors["country"] = "country must be a 2-letter ISO code"
        return None
    return country


def _validate_visibility(value, errors):
    if value in (None, ""):
        return "PRIVATE"
    try:
        visibility = coerce_visibility(value)
    except ValueError as error:
        errors["visibility"] = str(error)
        return None
    if visibility.value not in ("PUBLIC", "PRIVATE"):
        errors["visibility"] = "visibility must be one of PUBLIC, PRIVATE"
        return None
    return visibility.value


def _validated_team_values(data, *, partial, team=None):
    errors = {}
    values = {}

    if not partial or "name" in data:
        values["name"] = _validate_name(data.get("name"), errors)
    if "tag" in data:
        values["tag"] = _validate_tag(data.get("tag"), errors, team=team)
    if "description" in data:
        values["description"] = _validate_optional_text(
            data.get("description"), "description", errors, DESCRIPTION_MAX
        )
    if "country" in data:
        values["country"] = _validate_country(data.get("country"), errors)
    if "logo_url" in data:
        values["logo_url"] = parse_url(data.get("logo_url"), "logo_url", errors)
    if "visibility" in data or not partial:
        values["visibility"] = _validate_visibility(
            data.get("visibility"), errors
        )

    if errors:
        raise ApiError("Invalid team", status_code=400, fields=errors)
    return values


def _commit_or_conflict(message):
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ApiError(message, status_code=409) from error


def list_public_teams(search=None):
    query = (
        db.session.query(Team)
        .options(*_team_options())
        .filter(Team.visibility == "PUBLIC")
    )
    term = clean_str(search)
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(Team.name.ilike(pattern), Team.tag.ilike(pattern))
        )
    return query.order_by(Team.name, Team.id)


def ensure_team_visible(viewer, team, *, role=None):
    """Valida la visibilidad del equipo y devuelve el rol del espectador."""
    if role is None:
        role = _role_for(viewer, team)
    if not can_view(
        viewer,
        team.visibility,
        is_team_member=(role is not None),
    ):
        raise ApiError("Team is private", status_code=403)
    return role


def team_payload(team, viewer, *, role=None):
    """Construye el perfil del equipo aplicando visibilidad y permisos."""
    role = ensure_team_visible(viewer, team, role=role)
    is_member = role is not None

    pending = None
    if can_view_team_invitations(viewer, role):
        pending = _pending_invitations(team.id)

    return serialize_team(
        team,
        viewer_role=role.value if role is not None else None,
        is_member=is_member,
        permissions=_team_permissions(viewer, role, is_member),
        pending_invitations=pending,
    )


def get_team_for_viewer(viewer, team_id):
    team = _get_team(team_id)
    role = _role_for(viewer, team)
    return team, role


def get_my_team(user):
    membership = _get_membership(user.id)
    if membership is None:
        return None
    team = _get_team(membership.team_id)
    return team_payload(team, user, role=coerce_team_role(membership.role))


def team_members_payload(team):
    return [serialize_team_member(member) for member in _sorted_members(team)]


def create_team(user, data):
    if _get_membership(user.id) is not None:
        raise ApiError("You already belong to a team", status_code=409)

    values = _validated_team_values(data, partial=False)
    now = _utcnow()
    team = Team(
        **values,
        created_by_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(team)
    db.session.flush()

    db.session.add(
        TeamMember(
            team_id=team.id,
            user_id=user.id,
            role=TeamRole.CAPTAIN.value,
            joined_at=now,
        )
    )
    _cancel_pending_invitations_for_user(user.id, now)
    _commit_or_conflict("Team could not be created")
    return team


def update_team(user, team_id, data):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_edit_team(user, role):
        raise ApiError("You cannot edit this team", status_code=403)

    values = _validated_team_values(data, partial=True, team=team)
    for field, value in values.items():
        setattr(team, field, value)
    team.updated_at = _utcnow()
    _commit_or_conflict("Team could not be updated")
    return team


def _resolve_invitation_target(data):
    raw_user_id = data.get("user_id")
    username = clean_str(data.get("username"))

    if raw_user_id not in (None, ""):
        if isinstance(raw_user_id, bool):
            raise ApiError(
                "user_id must be an integer",
                status_code=400,
                fields={"user_id": "user_id must be an integer"},
            )
        try:
            target_id = int(raw_user_id)
        except (TypeError, ValueError) as error:
            raise ApiError(
                "user_id must be an integer",
                status_code=400,
                fields={"user_id": "user_id must be an integer"},
            ) from error
        target = db.session.get(User, target_id)
    elif username:
        target = (
            db.session.query(User)
            .filter(User.username.ilike(username))
            .first()
        )
    else:
        raise ApiError(
            "user_id or username is required",
            status_code=400,
            fields={"user_id": "user_id or username is required"},
        )

    if target is None:
        raise ApiError("User not found", status_code=404)
    return target


def invite_member(user, team_id, data):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_manage_invitations(user, role):
        raise ApiError("You cannot manage invitations", status_code=403)

    target = _resolve_invitation_target(data)
    if target.id == user.id:
        raise ApiError("You cannot invite yourself", status_code=400)

    if _get_membership(target.id, team.id) is not None:
        raise ApiError(
            "User is already a member of this team", status_code=409
        )
    if _get_membership(target.id) is not None:
        raise ApiError("User already belongs to a team", status_code=409)

    invitation_role = clean_str(data.get("role")).upper() or "PLAYER"
    if invitation_role not in INVITABLE_ROLES:
        raise ApiError(
            "Invalid invitation role",
            status_code=400,
            fields={
                "role": f"role must be one of {', '.join(INVITABLE_ROLES)}"
            },
        )

    pending = (
        db.session.query(TeamInvitation)
        .filter(
            TeamInvitation.team_id == team.id,
            TeamInvitation.user_id == target.id,
            TeamInvitation.status == "PENDING",
        )
        .first()
    )
    if pending is not None:
        raise ApiError(
            "A pending invitation already exists", status_code=409
        )

    invitation = TeamInvitation(
        team_id=team.id,
        user_id=target.id,
        invited_by_id=user.id,
        role=invitation_role,
        status="PENDING",
        created_at=_utcnow(),
    )
    db.session.add(invitation)
    _commit_or_conflict("A pending invitation already exists")
    return invitation


def _validate_status_filter(status):
    if status in (None, ""):
        return "PENDING"
    normalized = clean_str(status).upper()
    if normalized == "ALL":
        return None
    if normalized not in INVITATION_STATUSES:
        raise ApiError(
            "Invalid invitation status",
            status_code=400,
            fields={
                "status": (
                    "status must be one of "
                    f"{', '.join(INVITATION_STATUSES)}, ALL"
                )
            },
        )
    return normalized


def _invitations_query(*, team_id=None, user_id=None, status=None):
    query = db.session.query(TeamInvitation).options(
        *_invitation_options()
    )
    if team_id is not None:
        query = query.filter(TeamInvitation.team_id == team_id)
    if user_id is not None:
        query = query.filter(TeamInvitation.user_id == user_id)
    normalized = _validate_status_filter(status)
    if normalized is not None:
        query = query.filter(TeamInvitation.status == normalized)
    return query.order_by(
        TeamInvitation.created_at.desc(), TeamInvitation.id.desc()
    )


def list_team_invitations(user, team_id, status=None):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_view_team_invitations(user, role):
        raise ApiError("You cannot view invitations", status_code=403)
    return _invitations_query(team_id=team.id, status=status)


def list_my_invitations(user, status=None):
    return _invitations_query(user_id=user.id, status=status)


def accept_invitation(user, invitation_id):
    now = _utcnow()
    # Serializa aceptaciones simultáneas del mismo usuario en PostgreSQL.
    db.session.query(User.id).filter(User.id == user.id).with_for_update().first()
    invitation = (
        db.session.query(TeamInvitation)
        .options(*_invitation_options())
        .filter(TeamInvitation.id == invitation_id)
        .with_for_update()
        .first()
    )
    if invitation is None:
        raise ApiError("Invitation not found", status_code=404)
    if invitation.user_id != user.id:
        raise ApiError(
            "Invitation does not belong to you", status_code=403
        )
    if invitation.status != "PENDING":
        raise ApiError("Invitation is no longer pending", status_code=409)
    if _get_membership(user.id) is not None:
        raise ApiError("User already belongs to a team", status_code=409)

    role = (
        invitation.role
        if invitation.role in ("COACH", "PLAYER")
        else TeamRole.PLAYER.value
    )
    db.session.add(
        TeamMember(
            team_id=invitation.team_id,
            user_id=user.id,
            role=role,
            joined_at=now,
        )
    )
    invitation.status = "ACCEPTED"
    invitation.responded_at = now
    _cancel_pending_invitations_for_user(
        user.id, now, exclude_id=invitation.id
    )
    _commit_or_conflict("User already belongs to a team")
    return invitation


def reject_invitation(user, invitation_id):
    now = _utcnow()
    invitation = (
        db.session.query(TeamInvitation)
        .options(*_invitation_options())
        .filter(TeamInvitation.id == invitation_id)
        .with_for_update()
        .first()
    )
    if invitation is None:
        raise ApiError("Invitation not found", status_code=404)
    if invitation.user_id != user.id:
        raise ApiError(
            "Invitation does not belong to you", status_code=403
        )
    if invitation.status != "PENDING":
        raise ApiError("Invitation is no longer pending", status_code=409)

    invitation.status = "REJECTED"
    invitation.responded_at = now
    db.session.commit()
    return invitation


def cancel_invitation(user, team_id, invitation_id):
    team = _get_team(team_id)
    role = _role_for(user, team)
    # La autorización se resuelve antes de buscar la invitación para no revelar
    # su existencia a usuarios ajenos al equipo.
    if not can_manage_invitations(user, role):
        raise ApiError("You cannot cancel this invitation", status_code=403)

    invitation = (
        db.session.query(TeamInvitation)
        .options(*_invitation_options())
        .filter(
            TeamInvitation.id == invitation_id,
            TeamInvitation.team_id == team.id,
        )
        .first()
    )
    if invitation is None:
        raise ApiError("Invitation not found", status_code=404)

    if not can_cancel_invitation(
        user, team_role=role, invited_by_id=invitation.invited_by_id
    ):
        raise ApiError("You cannot cancel this invitation", status_code=403)
    if invitation.status != "PENDING":
        raise ApiError("Invitation is no longer pending", status_code=409)

    invitation.status = "CANCELLED"
    invitation.responded_at = _utcnow()
    db.session.commit()
    return invitation


def remove_member(user, team_id, member_user_id):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_remove_team_member(user, role):
        raise ApiError("You cannot remove members", status_code=403)

    membership = _get_membership(member_user_id, team.id)
    if membership is None:
        raise ApiError("Team member not found", status_code=404)
    if membership.user_id == user.id:
        raise ApiError(
            "Use leave to abandon your own team", status_code=400
        )
    if membership.role == TeamRole.CAPTAIN.value:
        raise ApiError(
            "Cannot remove the captain; transfer captaincy first",
            status_code=409,
        )

    team_lineup_service.detach_member(team.id, membership.user_id)
    db.session.delete(membership)
    db.session.commit()


def update_member_role(user, team_id, member_user_id, data):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_change_team_roles(user, role):
        raise ApiError("You cannot change member roles", status_code=403)

    membership = _get_membership(member_user_id, team.id)
    if membership is None:
        raise ApiError("Team member not found", status_code=404)
    if membership.user_id == user.id:
        raise ApiError("You cannot change your own role", status_code=400)
    if membership.role == TeamRole.CAPTAIN.value:
        raise ApiError(
            "Captaincy must be transferred, not reassigned", status_code=409
        )

    new_role = clean_str(data.get("role")).upper()
    if new_role not in ASSIGNABLE_ROLES:
        raise ApiError(
            "Invalid member role",
            status_code=400,
            fields={
                "role": (
                    "role must be one of "
                    f"{', '.join(ASSIGNABLE_ROLES)}; use transfer-captain "
                    "to assign the captaincy"
                )
            },
        )

    membership.role = new_role
    db.session.commit()
    return membership


def leave_team(user, team_id):
    team = _get_team(team_id)
    membership = _get_membership(user.id, team.id)
    if membership is None:
        raise ApiError("You are not a member of this team", status_code=403)

    if membership.role == TeamRole.CAPTAIN.value:
        others = (
            db.session.query(TeamMember)
            .filter(
                TeamMember.team_id == team.id,
                TeamMember.user_id != user.id,
            )
            .count()
        )
        if others > 0:
            raise ApiError(
                "Transfer captaincy before leaving the team",
                status_code=409,
            )
        # El capitán era el único integrante: el equipo queda vacío y se elimina.
        db.session.delete(team)
        db.session.commit()
        return

    team_lineup_service.detach_member(team.id, membership.user_id)
    db.session.delete(membership)
    db.session.commit()


def transfer_captain(user, team_id, data):
    team = _get_team(team_id)
    role = _role_for(user, team)
    if not can_transfer_captain(user, role):
        raise ApiError("You cannot transfer captaincy", status_code=403)

    raw_user_id = data.get("user_id")
    if raw_user_id in (None, ""):
        raise ApiError(
            "user_id is required",
            status_code=400,
            fields={"user_id": "user_id is required"},
        )
    try:
        target_user_id = int(raw_user_id)
    except (TypeError, ValueError) as error:
        raise ApiError(
            "user_id must be an integer",
            status_code=400,
            fields={"user_id": "user_id must be an integer"},
        ) from error

    target = _get_membership(target_user_id, team.id)
    if target is None:
        raise ApiError("Team member not found", status_code=404)
    if target.user_id == user.id:
        raise ApiError("You already are the captain", status_code=400)

    current = (
        db.session.query(TeamMember)
        .filter(
            TeamMember.team_id == team.id,
            TeamMember.role == TeamRole.CAPTAIN.value,
        )
        .with_for_update()
        .first()
    )
    if current is None:
        raise ApiError("Team has no captain", status_code=409)
    if current.id == target.id:
        raise ApiError("Member is already the captain", status_code=400)

    # Liberar el índice parcial antes de asignar el nuevo capitán.
    current.role = TeamRole.PLAYER.value
    db.session.flush()
    target.role = TeamRole.CAPTAIN.value
    _commit_or_conflict("Captaincy could not be transferred")
    return team
