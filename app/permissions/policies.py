"""Políticas centralizadas de autorización.

Matriz de permisos de equipo (Fase 2):

- CAPTAIN: editar el equipo, invitar, cancelar invitaciones, expulsar
  integrantes, asignar roles COACH/PLAYER, transferir la capitanía y abandonar
  el equipo (luego de transferir la capitanía si quedan integrantes).
- COACH: consultar la gestión, invitar jugadores/entrenadores y cancelar las
  invitaciones que él mismo creó. No edita el equipo, no expulsa, no cambia
  roles ni transfiere la capitanía.
- PLAYER: consultar el equipo y abandonarlo. No administra integrantes ni
  invitaciones.
- Administrador de la plataforma: puede realizar todas las acciones, incluso
  sobre equipos privados.

Matriz de permisos de alineaciones (Fase 3):

- Ver: cualquier espectador que pueda ver el equipo (la visibilidad se resuelve
  antes de llegar a la política).
- Crear, editar, asignar titulares/suplentes y roles, activar y desactivar:
  capitán, entrenador y administrador.
- Eliminar y elegir la alineación principal: solo capitán y administrador.

Las rutas y servicios no deben repetir estas reglas.
"""

from app.permissions.roles import TeamRole
from app.permissions.visibility import Visibility


def is_authenticated(user):
    return user is not None


def is_admin(user):
    return bool(user is not None and getattr(user, "is_admin", False))


def is_owner(user, owner_id):
    return bool(
        user is not None
        and owner_id is not None
        and getattr(user, "id", None) == owner_id
    )


def can_view(user, visibility, *, owner_id=None, is_team_member=False):
    """Resuelve lectura según visibilidad, propiedad y pertenencia al equipo."""
    level = visibility if isinstance(visibility, Visibility) else Visibility(visibility)

    if level is Visibility.PUBLIC:
        return True
    if user is None:
        return False
    if is_admin(user):
        return True
    if level is Visibility.PRIVATE:
        return is_owner(user, owner_id) or bool(is_team_member)
    if level is Visibility.TEAM:
        return bool(is_team_member)
    return False


def can_edit(user, *, owner_id=None, team_role=None, admin_only=False):
    """Resuelve edición. `admin_only` se usa para el catálogo global."""
    if user is None:
        return False
    if admin_only:
        return is_admin(user)
    if is_admin(user):
        return True
    if is_owner(user, owner_id):
        return True
    return team_role in (TeamRole.CAPTAIN, TeamRole.COACH)


def can_edit_team_resource(user, *, owner_id=None, team_role=None):
    return can_edit(user, owner_id=owner_id, team_role=team_role)


def can_manage_team(user, team_role):
    if user is None:
        return False
    return is_admin(user) or team_role == TeamRole.CAPTAIN


def can_edit_team(user, team_role=None):
    """Solo capitán o administrador editan los datos del equipo."""
    return can_manage_team(user, team_role)


def can_manage_invitations(user, team_role=None):
    """Capitán, entrenador y administrador pueden crear invitaciones."""
    if user is None:
        return False
    return is_admin(user) or team_role in (TeamRole.CAPTAIN, TeamRole.COACH)


def can_view_team_invitations(user, team_role=None):
    """La gestión de invitaciones es visible para capitán y entrenador."""
    return can_manage_invitations(user, team_role)


def can_cancel_invitation(user, *, team_role=None, invited_by_id=None):
    """Capitán/admin cancelan cualquiera; un entrenador solo las propias."""
    if user is None:
        return False
    if is_admin(user) or team_role == TeamRole.CAPTAIN:
        return True
    return team_role == TeamRole.COACH and is_owner(user, invited_by_id)


def can_remove_team_member(user, team_role=None):
    return can_manage_team(user, team_role)


def can_change_team_roles(user, team_role=None):
    return can_manage_team(user, team_role)


def can_transfer_captain(user, team_role=None):
    return can_manage_team(user, team_role)


def can_view_team_lineups(user, team_role=None):
    """Ver lineups siempre está permitido; la visibilidad la resuelve el equipo."""
    return True


def can_manage_team_lineups(user, team_role=None):
    """Capitán, entrenador y administrador crean y editan alineaciones."""
    if user is None:
        return False
    return is_admin(user) or team_role in (TeamRole.CAPTAIN, TeamRole.COACH)


def can_delete_team_lineup(user, team_role=None):
    """Solo capitán y administrador eliminan alineaciones."""
    return can_manage_team(user, team_role)


def can_set_primary_team_lineup(user, team_role=None):
    """Solo capitán y administrador eligen la lineup principal."""
    return can_manage_team(user, team_role)


def can_admin_catalog(user):
    return is_admin(user)
