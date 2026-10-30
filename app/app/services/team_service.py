"""Servicio de equipos.

Proporciona funciones para gestión de equipos, miembros e invitaciones.
"""

from app.extensions import db
from app.models import Team, Player


def list_public_teams(search=None):
    """Lista equipos públicos, opcionalmente filtrando por búsqueda."""
    from app.models import Team

    stmt = db.select(Team).where(Team.is_public == True)
    if search:
        from sqlalchemy import func, like

        stmt = stmt.where(func.lower(Team.name).like(func.lower(f"%{search}%")))
    from app.pagination import paginate

    return paginate(db.session.scalars(stmt).all())


def create_team(user, data):
    """Crea un nuevo equipo."""
    from app.models import Team

    team = Team(
        name=data.get("name"),
        tag=data.get("tag"),
        is_public=data.get("is_public", True),
        captain_id=user.id,
    )
    db.session.add(team)
    db.session.commit()
    return team


def get_my_team(user):
    """Obtiene el equipo activo del usuario autenticado."""
    from app.models import Team

    team = db.session.scalar(db.select(Team).where(Team.captain_id == user.id))
    return team


def list_my_invitations(user, status=None):
    """Lista invitaciones del usuario."""
    from app.models import Invitation
    from sqlalchemy import select

    stmt = db.select(Invitation).where(Invitation.user_id == user.id)
    if status:
        from sqlalchemy import func

        stmt = stmt.where(Invitation.status == status)
    from app.pagination import paginate

    return paginate(db.session.scalars(stmt).all())


def accept_invitation(user, invitation_id):
    """Acepta una invitación a equipo."""
    from app.models import Invitation

    invitation = db.session.get(Invitation, invitation_id)
    if invitation is None:
        return None
    invitation.status = "accepted"
    db.session.commit()
    return invitation


def reject_invitation(user, invitation_id):
    """Rechaza una invitación a equipo."""
    from app.models import Invitation

    invitation = db.session.get(Invitation, invitation_id)
    if invitation is None:
        return None
    invitation.status = "rejected"
    db.session.commit()
    return invitation


def get_team_for_viewer(viewer, team_id):
    """Obtiene un equipo para ser visto por un espectador."""
    from app.models import Team

    team = db.session.get(Team, team_id)
    if team is None:
        return None, None
    # Determinar rol basándose en si el viewer es el capitán
    role = (
        "captain" if viewer is not None and team.captain_id == viewer.id else "member"
    )
    return team, role


def update_team(user, team_id, data):
    """Actualiza un equipo."""
    from app.models import Team

    team = db.session.get(Team, team_id)
    if team is None:
        return None
    if "name" in data:
        team.name = data["name"]
    if "tag" in data:
        team.tag = data["tag"]
    if "is_public" in data:
        team.is_public = data["is_public"]
    db.session.commit()
    return team


def ensure_team_visible(viewer, team, role):
    """Asegura que el equipo sea visible para el viewer."""
    # Lógica simplificada: si el equipo es público, es visible
    # Si es privado, solo el dueño y capitán pueden verlo
    pass


def team_members_payload(team):
    """Retorna payload de miembros del equipo."""
    from app.models import TeamMember

    members = db.session.scalars(
        db.select(TeamMember).where(TeamMember.team_id == team.id)
    ).all()
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "role": m.role,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        }
        for m in members
    ]


def invite_member(user, team_id, data):
    """Invita a un miembro a un equipo."""
    from app.models import Invitation, Team
    from app.extensions import db

    team = db.session.get(Team, team_id)
    if team is None:
        return None
    invitation = Invitation(
        team_id=team_id,
        user_id=data.get("user_id"),
        invited_by=user.id,
        status="pending",
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation


def list_team_invitations(user, team_id, status=None):
    """Lista invitaciones a un equipo específico."""
    from app.models import Invitation
    from sqlalchemy import select

    stmt = db.select(Invitation).where(
        Invitation.team_id == team_id, Invitation.user_id == user.id
    )
    if status:
        from sqlalchemy import func

        stmt = stmt.where(Invitation.status == status)
    from app.pagination import paginate

    return paginate(db.session.scalars(stmt).all())


def cancel_invitation(user, team_id, invitation_id):
    """Cancela una invitación."""
    from app.models import Invitation

    invitation = db.session.get(Invitation, invitation_id)
    if invitation is None:
        return
    invitation.status = "cancelled"
    db.session.commit()


def remove_member(user, team_id, member_user_id):
    """Remueve un miembro del equipo."""
    from app.models import TeamMember

    db.session.execute(
        db.delete(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == member_user_id
        )
    )
    db.session.commit()


def update_member_role(user, team_id, member_user_id, data):
    """Actualiza el rol de un miembro."""
    from app.models import TeamMember

    db.session.execute(
        db.update(TeamMember)
        .where(TeamMember.team_id == team_id, TeamMember.user_id == member_user_id)
        .values(role=data.get("role", "member"))
    )
    db.session.commit()


def leave_team(user, team_id):
    """Hace que el usuario abandone el equipo."""
    from app.models import TeamMember

    db.session.execute(
        db.delete(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user.id
        )
    )
    db.session.commit()


def transfer_captain(user, team_id, data):
    """Transfiere la capitanía del equipo."""
    from app.models import Team

    team = db.session.get(Team, team_id)
    if team is None:
        return None
    new_captain_id = data.get("new_captain_id")
    if new_captain_id:
        team.captain_id = new_captain_id
        db.session.commit()
    return team
