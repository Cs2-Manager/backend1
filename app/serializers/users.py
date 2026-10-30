"""Representaciones de usuario según el contexto de la respuesta."""


def _base(user):
    return {
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat(),
    }


def serialize_user_public(user):
    """Datos aptos para perfiles y listados públicos. Nunca incluye email."""
    return _base(user)


def serialize_user_private(user):
    """Datos del propio usuario autenticado."""
    return {**_base(user), "email": user.email, "is_admin": bool(user.is_admin)}


def serialize_user_admin(user):
    """Datos completos para contextos administrativos."""
    return {
        **_base(user),
        "email": user.email,
        "is_admin": bool(user.is_admin),
    }
