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
    serialize_profile_owner,
    serialize_profile_public,
)
from app.services import match_service
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

    changed = False
    if profile.competitive is None:
        profile.competitive = PlayerCompetitiveProfile(status="UNRANKED")
        changed = True
    if profile.stats is None:
        profile.stats = PlayerStats()
        changed = True
    if changed and commit:
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


def _validate_nickname(profile, value, errors):
    nickname = clean_str(value)
    if not nickname:
        errors["nickname"] = "nickname is required"
        return None
    if len(nickname) > 80:
        errors["nickname"] = "nickname must be at most 80 characters"
        return None
    if any(ord(char) < 32 for char in nickname):
        errors["nickname"] = "nickname contains invalid characters"
        return None

    duplicate = (
        db.session.query(PlayerProfile.id)
        .filter(
            PlayerProfile.nickname == nickname,
            PlayerProfile.id != profile.id,
        )
        .first()
    )
    if duplicate:
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


def _sync_social_links(profile, links):
    existing = {link.platform: link for link in profile.social_links}
    for platform in SOCIAL_PLATFORMS:
        if platform not in links:
            continue
        url = links[platform]
        if url:
            if platform in existing:
                existing[platform].url = url
            else:
                profile.social_links.append(
                    PlayerSocialLink(platform=platform, url=url)
                )
        elif platform in existing:
            db.session.delete(existing[platform])


def update_own_profile(user, data):
    """Actualiza exclusivamente el perfil del usuario autenticado.

    Los campos de cuenta, privilegios, estadísticas y datos competitivos se
    ignoran aunque el cliente los envíe.
    """
    profile = ensure_profile(user)
    errors = {}

    nickname = None
    if "nickname" in data:
        nickname = _validate_nickname(profile, data.get("nickname"), errors)

    display_name = None
    if "display_name" in data:
        display_name = _validate_optional_text(
            data.get("display_name"), "display_name", errors, 80
        )

    country = None
    if "country" in data:
        raw_country = clean_str(data.get("country")).upper()
        if raw_country and not COUNTRY_REGEX.match(raw_country):
            errors["country"] = "country must be a 2-letter ISO code"
        else:
            country = raw_country or None

    bio = None
    if "bio" in data:
        bio = _validate_optional_text(data.get("bio"), "bio", errors, 500)

    avatar_url = None
    if "avatar_url" in data:
        avatar_url = parse_url(data.get("avatar_url"), "avatar_url", errors)

    steam_url = None
    if "steam_url" in data:
        steam_url = parse_url(
            data.get("steam_url"),
            "steam_url",
            errors,
            allowed_host="steamcommunity.com",
        )

    visibility = None
    if "visibility" in data:
        raw_visibility = data.get("visibility")
        if raw_visibility in (None, ""):
            visibility = Visibility.PRIVATE
        else:
            try:
                visibility = coerce_visibility(raw_visibility)
            except ValueError as error:
                errors["visibility"] = str(error)
            else:
                if visibility not in (Visibility.PUBLIC, Visibility.PRIVATE):
                    errors["visibility"] = (
                        "visibility must be one of PUBLIC, PRIVATE"
                    )

    social_links = None
    if "social_links" in data:
        social_links = _validate_social_links(data.get("social_links"), errors)

    if errors:
        raise ApiError("Invalid profile", status_code=400, fields=errors)

    if "nickname" in data:
        profile.nickname = nickname
    if "display_name" in data:
        profile.display_name = display_name
    if "country" in data:
        profile.country = country
    if "bio" in data:
        profile.bio = bio
    if "avatar_url" in data:
        profile.avatar_url = avatar_url
    if "steam_url" in data:
        profile.steam_url = steam_url
    if "visibility" in data:
        profile.visibility = visibility.value
    if social_links is not None:
        _sync_social_links(profile, social_links)

    profile.updated_at = _utcnow()
    touch_activity(profile)
    db.session.commit()
    return profile


def profile_payload(profile, *, owner=False):
    """Construye la respuesta completa con secciones separadas."""
    stats = match_service.ensure_stats(profile)
    recent_matches = match_service.list_matches(
        profile, limit=RECENT_MATCH_LIMIT
    )
    map_performance = match_service.map_performance(profile)
    serializer = serialize_profile_owner if owner else serialize_profile_public
    return serializer(
        profile,
        stats=stats,
        map_performance=map_performance,
        recent_matches=recent_matches,
    )


def is_owner(viewer, user_id):
    return user_is_owner(viewer, user_id)
