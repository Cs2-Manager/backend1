"""Rutas del perfil competitivo.

- `/api/profile`: perfil propio y edición (JWT).
- `/api/players`: directorio público de perfiles públicos.
- `/api/players/<id>`: perfil público o privado según visibilidad.
- `/api/players/<id>/matches`: historial con la misma política de visibilidad.
"""

from flask import Blueprint, jsonify, request

from app.pagination import paginate
from app.security import admin_required, jwt_optional, jwt_required
from app.serializers import serialize_match, serialize_profile_summary
from app.services import match_service, profile_service

profiles_bp = Blueprint("profiles", __name__, url_prefix="/api")


@profiles_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_own_profile(user):
    profile = profile_service.get_own_profile(user)
    return (
        jsonify({"profile": profile_service.profile_payload(profile, owner=True)}),
        200,
    )


@profiles_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile(user):
    data = request.get_json(silent=True) or {}
    profile = profile_service.update_own_profile(user, data)
    return (
        jsonify({"profile": profile_service.profile_payload(profile, owner=True)}),
        200,
    )


@profiles_bp.route("/players", methods=["GET"])
def list_players():
    query = profile_service.list_public_profiles(request.args.get("search"))
    items, meta = paginate(query)
    return (
        jsonify(
            {
                "players": [
                    serialize_profile_summary(profile, profile.stats)
                    for profile in items
                ],
                "meta": meta,
            }
        ),
        200,
    )


@profiles_bp.route("/players/<int:user_id>", methods=["GET"])
@jwt_optional()
def get_player(viewer, user_id):
    profile = profile_service.get_profile_for_viewer(viewer, user_id)
    owner = profile_service.is_owner(viewer, user_id)
    return (
        jsonify({"profile": profile_service.profile_payload(profile, owner=owner)}),
        200,
    )


@profiles_bp.route("/players/<int:user_id>/matches", methods=["GET"])
@jwt_optional()
def get_player_matches(viewer, user_id):
    profile = profile_service.get_profile_for_viewer(viewer, user_id)
    items, meta = paginate(match_service.matches_query(profile))
    return (
        jsonify({"matches": [serialize_match(match) for match in items], "meta": meta}),
        200,
    )


@profiles_bp.route("/players/<int:user_id>/matches", methods=["POST"])
@admin_required()
def record_player_match(_admin, user_id):
    """Ingesta administrativa de una partida real.

    No existe integración automática con CS2/Steam en esta fase, por lo que la
    única vía de escritura es esta ingesta controlada. El jugador no puede
    fabricar sus propias estadísticas.
    """
    profile = profile_service.get_profile_for_viewer(_admin, user_id)
    data = request.get_json(silent=True) or {}
    match = match_service.record_match(profile, data)
    return jsonify({"match": serialize_match(match)}), 201
