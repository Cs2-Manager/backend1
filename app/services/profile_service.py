"""Lógica de perfiles competitivos y privacidad."""

import re
from datetime import datetime, timezone

from sqlalchemy import or_

from app.errors import ApiError
from app.extensions import db
from app.models.player_profile import (
    SOCIAL_PLATFORMS,
    PlayerCompetitiveProfile,
    PlayerProfile,
    PlayerSocialLink,
    PlayerStats,
)
from app.models.user import User
from app.permissions import (
    Visibility,
    can_view,
    coerce_visibility,
    is_owner as user_is_owner,
)
from app.serializers import (
    build_provenance,
    serialize_profile_owner,
    serialize_profile_public,
)
from app.services import match_service
from app.services import matchmaking_service
from app.validators import clean_str, parse_url

COUNTRY_REGEX = re.compile(r"^[A-Z]{2}$")
RECENT_MATCH_LIMIT = 10


def _utcnow():
    return datetime.now(timezone.utc)


def create_profile_for_user(user):
    """Crea el perfil y sus agregados vacíos. No confirma la transacción."""
    now = _utcnow()
    profile = PlayerProfile(
        user_id=user.id,
        nickname=user.username,
        display_name=user.username,
        visibility=Visibility.PRIVATE.value,
        last_active_at=now,
        created_at=now,
        updated_at=now,
    )
    profile.competitive = PlayerCompetitiveProfile(
        status="UNRANKED", updated_at=now
    )
    profile.stats = PlayerStats(updated_at=now)
    db.session.add(profile)
    return profile


def _ensure_relations(profile):
    changed = False
    if profile.competitive is None:
        profile.competitive = PlayerCompetitiveProfile(status="UNRANKED")
        changed = True
    if profile.stats is None:
        profile.stats = PlayerStats()
        changed = True
    return changed


def ensure_profile(user, *, commit=True):
    """Devuelve el perfil del usuario y completa filas faltantes si es necesario."""
    profile = (
        db.session.query(PlayerProfile).filter_by(user_id=user.id).first()
    )
    if profile is None:
        profile = create_profile_for_user(user)
        if commit:
            db.session.commit()
        return profile

    if _ensure_relations(profile) and commit:
        db.session.commit()
    return profile


def touch_activity(profile):
    """Registra actividad confiable (login o edición de perfil)."""
    profile.last_active_at = _utcnow()


def get_own_profile(user):
    return ensure_profile(user)


def get_profile_for_viewer(viewer, user_id):
    """Carga un perfil y aplica la política de visibilidad de Fase 0."""
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("Player not found", status_code=404)

    profile = ensure_profile(user)
    if not can_view(viewer, profile.visibility, owner_id=user.id):
        raise ApiError("Profile is private", status_code=403)
    return profile


def list_public_profiles(search=None):
    query = (
        db.session.query(PlayerProfile)
        .join(User, PlayerProfile.user_id == User.id)
        .filter(PlayerProfile.visibility == Visibility.PUBLIC.value)
    )
    term = clean_str(search)
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(
                User.username.ilike(pattern),
                PlayerProfile.nickname.ilike(pattern),
                PlayerProfile.display_name.ilike(pattern),
            )
        )
    return query.order_by(PlayerProfile.nickname)


def _nickname_problem(nickname):
    if not nickname:
        return "nickname is required"
    if len(nickname) > 80:
        return "nickname must be at most 80 characters"
    if any(ord(char) < 32 for char in nickname):
        return "nickname contains invalid characters"
    return None


def _nickname_taken(profile, nickname):
    duplicate = (
        db.session.query(PlayerProfile.id)
        .filter(
            PlayerProfile.nickname == nickname,
            PlayerProfile.id != profile.id,
        )
        .first()
    )
    return duplicate is not None


def _validate_nickname(profile, value, errors):
    nickname = clean_str(value)
    problem = _nickname_problem(nickname)
    if problem:
        errors["nickname"] = problem
        return None
    if _nickname_taken(profile, nickname):
        errors["nickname"] = "nickname is already in use"
        return None
    return nickname


def _validate_optional_text(value, field, errors, max_length):
    text = clean_str(value)
    if not text:
        return None
    if len(text) > max_length:
        errors[field] = f"{field} must be at most {max_length} characters"
        return None
    return text


def _validate_social_links(value, errors):
    if value is None:
        return None
    if not isinstance(value, dict):
        errors["social_links"] = "social_links must be an object"
        return None

    links = {}
    for platform, url in value.items():
        if platform not in SOCIAL_PLATFORMS:
            errors["social_links"] = (
                f"social_links must use {', '.join(SOCIAL_PLATFORMS)}"
            )
            continue
        links[platform] = parse_url(url, platform, errors)
    return links


def _set_social_link(profile, existing, platform, url):
    if not url:
        if platform in existing:
            db.session.delete(existing[platform])
        return
    if platform in existing:
        existing[platform].url = url
        return
    profile.social_links.append(PlayerSocialLink(platform=platform, url=url))


def _sync_social_links(profile, links):
    existing = {link.platform: link for link in profile.social_links}
    for platform in SOCIAL_PLATFORMS:
        if platform in links:
            _set_social_link(profile, existing, platform, links[platform])


def _country_value(value, errors):
    raw_country = clean_str(value).upper()
    if raw_country and not COUNTRY_REGEX.match(raw_country):
        errors["country"] = "country must be a 2-letter ISO code"
        return None
    return raw_country or None


def _visibility_value(value, errors):
    if value in (None, ""):
        return Visibility.PRIVATE
    try:
        visibility = coerce_visibility(value)
    except ValueError as error:
        errors["visibility"] = str(error)
        return None
    if visibility not in (Visibility.PUBLIC, Visibility.PRIVATE):
        errors["visibility"] = "visibility must be one of PUBLIC, PRIVATE"
        return None
    return visibility


def _steam_url_value(value, errors):
    return parse_url(
        value,
        "steam_url",
        errors,
        allowed_host="steamcommunity.com",
    )


_PROFILE_TEXT_FIELDS = (
    ("display_name", 80),
    ("bio", 500),
)


def _profile_text_values(data, errors):
    values = {}
    for field, maximum in _PROFILE_TEXT_FIELDS:
        if field in data:
            values[field] = _validate_optional_text(
                data.get(field), field, errors, maximum
            )
    return values


def _profile_url_values(data, errors):
    values = {}
    if "avatar_url" in data:
        values["avatar_url"] = parse_url(
            data.get("avatar_url"), "avatar_url", errors
        )
    if "steam_url" in data:
        values["steam_url"] = _steam_url_value(data.get("steam_url"), errors)
    return values


def _profile_values(profile, data, errors):
    values = {}
    if "nickname" in data:
        values["nickname"] = _validate_nickname(
            profile, data.get("nickname"), errors
        )
    values.update(_profile_text_values(data, errors))
    if "country" in data:
        values["country"] = _country_value(data.get("country"), errors)
    values.update(_profile_url_values(data, errors))
    if "visibility" in data:
        values["visibility"] = _visibility_value(data.get("visibility"), errors)
    if "social_links" in data:
        values["social_links"] = _validate_social_links(
            data.get("social_links"), errors
        )
    return values


def _apply_profile_values(profile, values):
    social_links = values.pop("social_links", None)
    for field, value in values.items():
        if field == "visibility":
            profile.visibility = value.value
        else:
            setattr(profile, field, value)
    if social_links is not None:
        _sync_social_links(profile, social_links)


def update_own_profile(user, data):
    """Actualiza exclusivamente el perfil del usuario autenticado.

    Los campos de cuenta, privilegios, estadísticas y datos competitivos se
    ignoran aunque el cliente los envíe.
    """
    profile = ensure_profile(user)
    errors = {}
    values = _profile_values(profile, data, errors)

    if errors:
        raise ApiError("Invalid profile", status_code=400, fields=errors)

    _apply_profile_values(profile, values)
    profile.updated_at = _utcnow()
    touch_activity(profile)
    db.session.commit()
    return profile


def profile_payload(profile, *, owner=False):
    """Construye la respuesta completa con secciones separadas."""
    # Import local para evitar el ciclo profile_service <-> steam_service
    # (steam_service usa create_profile_for_user al registrar vía Steam).
    from app.services import faceit_service, steam_service

    stats = match_service.ensure_stats(profile)
    recent_matches = match_service.list_matches(
        profile, limit=RECENT_MATCH_LIMIT
    )
    map_performance = match_service.map_performance(profile)
    steam = steam_service.build_steam_section(profile.user, owner=owner)
    matchmaking = matchmaking_service.build_section(
        profile.user, owner=owner
    )
    faceit = faceit_service.build_section(profile.user, owner=owner)
    provenance = build_provenance(
        stats=stats,
        map_performance=map_performance,
        recent_matches=recent_matches,
        steam=steam,
        matchmaking=matchmaking,
        faceit=faceit,
    )
    serializer = serialize_profile_owner if owner else serialize_profile_public
    return serializer(
        profile,
        stats=stats,
        map_performance=map_performance,
        recent_matches=recent_matches,
        steam=steam,
        matchmaking=matchmaking,
        faceit=faceit,
        provenance=provenance,
    )


def is_owner(viewer, user_id):
    return user_is_owner(viewer, user_id)
