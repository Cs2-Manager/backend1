"""Serializadores de equipos, integrantes e invitaciones.

La información de usuario se limita a datos públicos: nunca email, hash de
contraseña ni privilegios administrativos. Las invitaciones solo se incluyen
cuando el servicio ya validó que el espectador puede administrarlas.
"""

ROLE_ORDER = {"CAPTAIN": 0, "COACH": 1, "PLAYER": 2}


def _iso(value):
    return value.isoformat() if value is not None else None


def _profile_of(user):
    return getattr(user, "profile", None)


def serialize_team_user(user):
    """Resumen público de un usuario dentro de un equipo."""
    if user is None:
        return None
    profile = _profile_of(user)
    return {
        "id": user.id,
        "username": user.username,
        "nickname": getattr(profile, "nickname", None) or user.username,
        "display_name": getattr(profile, "display_name", None),
        "avatar_url": getattr(profile, "avatar_url", None),
        "country": getattr(profile, "country", None),
    }


def _sorted_members(team):
    return sorted(
        team.members,
        key=lambda member: (
            ROLE_ORDER.get(member.role, 3),
            member.joined_at or member.id,
        ),
    )


def _captain(members):
    return next((member for member in members if member.role == "CAPTAIN"), None)


def serialize_team_member(member):
    return {
        "id": member.id,
        "role": member.role,
        "joined_at": _iso(member.joined_at),
        "user": serialize_team_user(member.user),
    }


def serialize_team_summary(team):
    """Datos para el directorio y para referencias desde invitaciones."""
    members = _sorted_members(team)
    captain = _captain(members)
    return {
        "id": team.id,
        "name": team.name,
        "tag": team.tag,
        "logo_url": team.logo_url,
        "country": team.country,
        "visibility": team.visibility,
        "created_at": _iso(team.created_at),
        "member_count": len(members),
        "captain": serialize_team_user(captain.user) if captain else None,
    }


def serialize_team(
    team,
    *,
    viewer_role=None,
    is_member=False,
    permissions=None,
    pending_invitations=None,
):
    """Perfil completo del equipo con acciones calculadas por el servicio."""
    members = _sorted_members(team)
    captain = _captain(members)
    payload = {
        "id": team.id,
        "name": team.name,
        "tag": team.tag,
        "logo_url": team.logo_url,
        "description": team.description,
        "country": team.country,
        "visibility": team.visibility,
        "created_at": _iso(team.created_at),
        "updated_at": _iso(team.updated_at),
        "member_count": len(members),
        "is_member": bool(is_member),
        "my_role": viewer_role,
        "captain": serialize_team_user(captain.user) if captain else None,
        "coaches": [
            serialize_team_member(member)
            for member in members
            if member.role == "COACH"
        ],
        "players": [
            serialize_team_member(member)
            for member in members
            if member.role == "PLAYER"
        ],
        "members": [serialize_team_member(member) for member in members],
        "permissions": permissions or {},
    }
    if pending_invitations is not None:
        payload["pending_invitations"] = [
            serialize_invitation(invitation) for invitation in pending_invitations
        ]
    return payload


def serialize_invitation(invitation):
    return {
        "id": invitation.id,
        "role": invitation.role,
        "status": invitation.status,
        "created_at": _iso(invitation.created_at),
        "responded_at": _iso(invitation.responded_at),
        "team": serialize_team_summary(invitation.team),
        "invited_by": serialize_team_user(invitation.invited_by),
        "user": serialize_team_user(invitation.user),
    }
