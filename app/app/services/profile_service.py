"""Servicio de perfiles.

Proporciona funciones para obtener y gestionar perfiles de jugadores.
"""


def get_own_profile(user):
    """Obtiene el perfil propio del usuario."""
    from app.models import Player
    from sqlalchemy import select

    stmt = select(Player).where(Player.user_id == user.id)
    from app.extensions import db

    player = db.session.scalar(stmt)
    if player is None:
        return None
    return {
        "id": player.id,
        "user_id": player.user_id,
        "nickname": player.nickname,
        "rank": player.rank,
        "level": player.level,
        "wins": player.wins,
        "losses": player.losses,
    }


def list_public_profiles(search=None):
    """Lista perfiles públicos, opcionalmente filtrando por búsqueda."""
    from app.models import Player
    from app.extensions import db
    from sqlalchemy import select, func, like

    stmt = select(Player).where(Player.is_public == True)
    if search:
        stmt = stmt.where(like(func.lower(Player.nickname), f"%{search.lower()}%"))
    from app.pagination import paginate

    return paginate(db.session.execute(stmt).scalars().all())


def get_profile_for_viewer(viewer, user_id):
    """Obtiene un perfil para ser visto por un espectador, respetando visibilidad."""
    from app.models import Player
    from app.extensions import db
    from sqlalchemy import select

    stmt = select(Player).where(Player.id == user_id)
    player = db.session.scalar(stmt)
    if player is None:
        return None
    # Lógica simplified: si el perfil es público, cualquiera puede verlo
    # Si es privado, solo el dueño puede verlo
    is_owner = viewer is not None and viewer.id == player.user_id
    if player.is_public or is_owner:
        return {
            "id": player.id,
            "user_id": player.user_id,
            "nickname": player.nickname,
            "rank": player.rank,
            "level": player.level,
            "is_public": player.is_public,
        }
    return None


def is_owner(viewer, user_id):
    """Verifica si el viewer es el dueño del perfil."""
    from app.extensions import db
    from app.models import Player

    stmt = select(Player).where(Player.id == user_id)
    player = db.session.scalar(stmt)
    return viewer is not None and viewer.id == player.user_id


def update_own_profile(user, data):
    """Actualiza el perfil propio del usuario."""
    from app.models import Player
    from app.extensions import db
    from app.validators import update_profile as validate_profile

    stmt = select(Player).where(Player.user_id == user.id)
    player = db.session.scalar(stmt)
    if player is None:
        return None
    # Actualizar campos permitidos
    allowed = ["nickname", "rank", "level"]
    for field in allowed:
        if field in data:
            setattr(player, field, data[field])
    db.session.commit()
    return {
        "id": player.id,
        "user_id": player.user_id,
        "nickname": player.nickname,
        "rank": player.rank,
        "level": player.level,
    }


def matches_query(profile):
    """Retorna una consulta de matches para un perfil."""
    from app.models import Match
    from app.extensions import db
    from sqlalchemy import select

    stmt = select(Match).where(Match.profile_id == profile.get("id") if profile else 0)
    return db.session.execute(stmt).scalars().all()
