"""Lógica de vinculación, autenticación y sincronización con Steam.

No se inventan estadísticas: Steam Web API solo permite verificar identidad
pública y tiempo de juego. Las estadísticas competitivas de CS2 quedan
explícitamente como `UNAVAILABLE` en los serializadores.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from flask import current_app

from app.errors import ApiError
from app.extensions import db
from app.models.player_profile import PlayerProfile
from app.models.steam import (
    STEAM_AUTH_INTENTS,
    STEAM_CS2_APP_ID,
    SteamAccount,
    SteamAuthRequest,
    SteamGameStats,
)
from app.models.user import User
from app.security import generate_token, hash_password
from app.serializers import serialize_user_private
from app.serializers.steam import serialize_steam_section
from app.services import profile_service, steam_api, steam_openid
from app.utils.time_utils import as_utc, utcnow

USERNAME_INVALID = re.compile(r"[^A-Za-z0-9_.-]+")
MAX_USERNAME_LENGTH = 80


def _iso(value):
    value = as_utc(value)
    return value.isoformat() if value is not None else None


def _hash(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _base_url():
    return str(
        current_app.config.get("STEAM_PUBLIC_BASE_URL", "http://localhost")
    ).rstrip("/")


def _callback_url():
    return f"{_base_url()}/api/auth/steam/callback"


def frontend_callback_url(**params):
    url = f"{_base_url()}/steam/callback"
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def is_configured():
    return steam_api.is_configured()


def _api_error_status(error):
    if error.code == "not_configured":
        return 503
    if error.code == "rate_limited":
        return 429
    if error.code == "forbidden":
        return 502
    if error.code == "not_found":
        return 404
    return 502


def _raise_api_error(error):
    raise ApiError(error.message, status_code=_api_error_status(error))


def _purge_old_requests(now):
    cutoff = now - timedelta(days=1)
    (
        db.session.query(SteamAuthRequest)
        .filter(SteamAuthRequest.expires_at < cutoff)
        .delete(synchronize_session=False)
    )


def _find_state_request(state):
    if not state:
        return None
    return (
        db.session.query(SteamAuthRequest)
        .filter(SteamAuthRequest.state_hash == _hash(state))
        .first()
    )


def _find_handoff_request(code):
    if not code:
        return None
    return (
        db.session.query(SteamAuthRequest)
        .filter(SteamAuthRequest.handoff_hash == _hash(code))
        .first()
    )


def _validate_link_intent(user):
    if user is None:
        raise ApiError("Authentication required", status_code=401)
    if user.steam_account is not None:
        raise ApiError(
            "A Steam account is already linked", status_code=409
        )


def _validate_start_intent(intent, user):
    if intent not in STEAM_AUTH_INTENTS:
        raise ApiError("Invalid Steam authentication intent", status_code=400)
    if not is_configured():
        raise ApiError(
            "Steam integration is not configured", status_code=503
        )
    if intent == "LINK":
        _validate_link_intent(user)


def start_intent(intent, user=None):
    """Crea la solicitud OpenID y devuelve la URL oficial de Steam."""
    _validate_start_intent(intent, user)

    now = utcnow()
    _purge_old_requests(now)
    state = secrets.token_urlsafe(32)
    return_to = f"{_callback_url()}?{urlencode({'state': state})}"
    request = SteamAuthRequest(
        state_hash=_hash(state),
        intent=intent,
        user_id=user.id if user is not None else None,
        return_to=return_to,
        expires_at=now
        + timedelta(
            seconds=int(
                current_app.config.get(
                    "STEAM_AUTH_REQUEST_TTL_SECONDS", 600
                )
            )
        ),
        created_at=now,
    )
    db.session.add(request)
    db.session.commit()

    return steam_openid.build_login_url(return_to, _base_url())


def _link_conflict_error(user, steam_id):
    existing = _account_by_steam_id(steam_id)
    if existing is not None and existing.user_id != user.id:
        return "account_conflict"
    if (
        user.steam_account is not None
        and user.steam_account.steam_id != steam_id
    ):
        return "account_conflict"
    return None


def _handoff_values(request, now):
    handoff = secrets.token_urlsafe(32)
    request.handoff_hash = _hash(handoff)
    request.handoff_expires_at = now + timedelta(
        seconds=int(current_app.config.get("STEAM_HANDOFF_TTL_SECONDS", 120))
    )
    request.handoff_used_at = None
    return handoff


def _request_user(request):
    if request.user_id:
        return db.session.get(User, request.user_id)
    return None


def _link_callback_error(request, steam_id):
    if request.intent != "LINK":
        return None
    user = _request_user(request)
    if user is None:
        return "link_requires_login"
    return _link_conflict_error(user, steam_id)


def process_callback(values):
    """Valida la respuesta de Steam y devuelve la URL final del frontend."""
    request = _find_state_request(values.get("state"))
    now = utcnow()
    if not _state_request_valid(request, now):
        return frontend_callback_url(error="invalid_state")

    try:
        steam_id = steam_openid.verify_response(values, request.return_to)
    except steam_openid.SteamOpenIDError as error:
        request.consumed_at = now
        db.session.commit()
        return frontend_callback_url(error=error.code)

    request.consumed_at = now
    request.steam_id = steam_id

    error = _link_callback_error(request, steam_id)
    if error:
        db.session.commit()
        return frontend_callback_url(error=error)

    handoff = _handoff_values(request, now)
    db.session.commit()
    return frontend_callback_url(handoff=handoff)


def _account_by_steam_id(steam_id):
    return (
        db.session.query(SteamAccount)
        .filter(SteamAccount.steam_id == str(steam_id))
        .first()
    )


def _apply_summary(account, summary):
    account.persona_name = summary.get("persona_name")
    account.profile_url = summary.get("profile_url")
    account.avatar_url = summary.get("avatar_url")
    account.avatar_medium_url = summary.get("avatar_medium_url")
    account.avatar_full_url = summary.get("avatar_full_url")
    account.persona_state = summary.get("persona_state")
    account.community_visibility_state = summary.get(
        "community_visibility_state"
    )
    account.profile_created_at = _timestamp_to_datetime(
        summary.get("profile_created_at")
    )
    account.last_logoff_at = _timestamp_to_datetime(
        summary.get("last_logoff_at")
    )


def _timestamp_to_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _sanitize_username(value, steam_id):
    base = USERNAME_INVALID.sub("", str(value or "")).strip("._-")
    if not base:
        base = "steam_player"
    return base[:MAX_USERNAME_LENGTH], str(steam_id)


def _unique_username(value, steam_id):
    base, _ = _sanitize_username(value, steam_id)
    suffix = str(steam_id)[-6:]
    candidate = base[: MAX_USERNAME_LENGTH - len(suffix) - 1]
    if _username_exists(candidate):
        candidate = f"{base[: MAX_USERNAME_LENGTH - len(suffix) - 1]}_{suffix}"
    counter = 1
    while _username_exists(candidate):
        tail = f"_{suffix}{counter}"
        candidate = f"{base[: MAX_USERNAME_LENGTH - len(tail)]}{tail}"
        counter += 1
    return candidate


def _username_exists(username):
    return (
        db.session.query(User.id).filter(User.username == username).first()
        is not None
    )


def _unique_nickname(value, steam_id):
    base, _ = _sanitize_username(value, steam_id)
    suffix = str(steam_id)[-6:]
    candidate = base[: MAX_USERNAME_LENGTH - len(suffix) - 1]
    if _nickname_exists(candidate):
        candidate = f"{base[: MAX_USERNAME_LENGTH - len(suffix) - 1]}_{suffix}"
    counter = 1
    while _nickname_exists(candidate):
        tail = f"_{suffix}{counter}"
        candidate = f"{base[: MAX_USERNAME_LENGTH - len(tail)]}{tail}"
        counter += 1
    return candidate


def _nickname_exists(nickname):
    return (
        db.session.query(PlayerProfile.id)
        .filter(PlayerProfile.nickname == nickname)
        .first()
        is not None
    )


def _create_user_from_summary(summary):
    steam_id = str(summary["steam_id"])
    persona = (summary.get("persona_name") or f"Steam {steam_id[-6:]}")[:80]
    user = User(
        username=_unique_username(persona, steam_id),
        email=f"steam_{steam_id}@steam.invalid",
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    nickname = _unique_nickname(persona, steam_id)
    db.session.add(user)
    db.session.flush()

    profile = profile_service.create_profile_for_user(user)
    profile.nickname = nickname
    profile.display_name = persona

    account = SteamAccount(user_id=user.id, steam_id=steam_id)
    _apply_summary(account, summary)
    db.session.add(account)
    db.session.flush()
    return user


def _ensure_linkable_account(user, existing, steam_id):
    if existing is not None and existing.user_id != user.id:
        raise ApiError(
            "This Steam account is already linked to another user",
            status_code=409,
        )
    if (
        user.steam_account is not None
        and user.steam_account.steam_id != steam_id
    ):
        raise ApiError(
            "This user already has a different Steam account linked",
            status_code=409,
        )


def _link_account(user, summary):
    steam_id = str(summary["steam_id"])
    existing = _account_by_steam_id(steam_id)
    _ensure_linkable_account(user, existing, steam_id)

    account = user.steam_account or existing
    if account is None:
        account = SteamAccount(user_id=user.id, steam_id=steam_id)
        db.session.add(account)
    _apply_summary(account, summary)
    return account


def _state_request_valid(request, now):
    if request is None:
        return False
    if request.consumed_at is not None:
        return False
    return as_utc(request.expires_at) >= now


def _handoff_state_ok(request):
    if request is None:
        return False
    if request.consumed_at is None:
        return False
    return request.handoff_used_at is None and bool(request.steam_id)


def _handoff_timing_ok(request, now):
    if request.handoff_expires_at is None:
        return False
    return as_utc(request.handoff_expires_at) >= now


def _valid_handoff(request, now):
    return _handoff_state_ok(request) and _handoff_timing_ok(request, now)


def _summary_or_none(steam_id):
    try:
        return steam_api.fetch_player_summaries(steam_id)
    except steam_api.SteamApiError:
        return None


def _login_user(steam_id):
    account = _account_by_steam_id(steam_id)
    if account is not None:
        summary = _summary_or_none(steam_id)
        if summary is not None:
            _apply_summary(account, summary)
        return account.user, False

    try:
        summary = steam_api.fetch_player_summaries(steam_id)
    except steam_api.SteamApiError as error:
        _raise_api_error(error)
    if summary is None:
        raise ApiError(
            "Steam did not return a player summary", status_code=502
        )
    return _create_user_from_summary(summary), True


def _link_user(request, steam_id):
    user = (
        db.session.get(User, request.user_id) if request.user_id else None
    )
    if user is None:
        raise ApiError("The local account no longer exists", status_code=404)
    existing = _account_by_steam_id(steam_id)
    _ensure_linkable_account(user, existing, steam_id)
    try:
        summary = steam_api.fetch_player_summaries(steam_id)
    except steam_api.SteamApiError as error:
        _raise_api_error(error)
    if summary is None:
        raise ApiError(
            "Steam did not return a player summary", status_code=502
        )
    _link_account(user, summary)
    return user, False


def _resolve_handoff_user(request, steam_id):
    if request.intent == "LOGIN":
        return _login_user(steam_id)
    if request.intent == "LINK":
        return _link_user(request, steam_id)
    # pragma: no cover - protegido por el modelo
    raise ApiError("Invalid Steam intent", status_code=400)


def exchange_handoff(code):
    """Canjea un handoff de un solo uso y emite el JWT de la plataforma."""
    request = _find_handoff_request(code)
    now = utcnow()
    if not _valid_handoff(request, now):
        raise ApiError(
            "Invalid or expired Steam authentication", status_code=400
        )

    if not is_configured():
        raise ApiError(
            "Steam integration is not configured", status_code=503
        )

    user, created = _resolve_handoff_user(request, request.steam_id)
    request.handoff_used_at = now
    db.session.commit()

    return {
        "token": generate_token(user),
        "token_type": "Bearer",
        "user": serialize_user_private(user),
        "created": created,
        "intent": request.intent,
        "steam": build_steam_section(user, owner=True),
    }


def unlink_account(user):
    account = user.steam_account
    if account is None:
        raise ApiError("No Steam account is linked", status_code=404)
    db.session.delete(account)
    db.session.commit()
    return user


def _upsert_cs2_stats(account, game):
    stat = account.cs2_stats()
    if stat is None:
        stat = SteamGameStats(
            steam_account_id=account.id,
            app_id=STEAM_CS2_APP_ID,
        )
        db.session.add(stat)
    stat.name = game.get("name")
    stat.playtime_forever_minutes = game.get("playtime_forever_minutes")
    stat.playtime_two_weeks_minutes = game.get(
        "playtime_two_weeks_minutes"
    )
    stat.last_played_at = _timestamp_to_datetime(game.get("last_played"))
    icon_hash = game.get("img_icon_url")
    stat.icon_url = (
        "https://media.steampowered.com/steamcommunity/public/images/apps/"
        f"{STEAM_CS2_APP_ID}/{icon_hash}.jpg"
        if icon_hash
        else None
    )
    stat.source = "VERIFIED_STEAM"
    stat.fetched_at = utcnow()
    return stat


def _delete_cs2_stats(account):
    stat = account.cs2_stats()
    if stat is not None:
        db.session.delete(stat)
        db.session.flush()


def _sync_interval_state(account, now):
    interval = int(
        current_app.config.get("STEAM_SYNC_MIN_INTERVAL_SECONDS", 300)
    )
    last_sync_at = as_utc(account.last_sync_at)
    if last_sync_at is None:
        return interval, None
    elapsed = (now - last_sync_at).total_seconds()
    if elapsed < interval:
        return interval, max(1, int(interval - elapsed))
    return interval, None


def _owned_games_outcome(account):
    try:
        owned = steam_api.fetch_owned_games(
            account.steam_id, app_id=STEAM_CS2_APP_ID
        )
    except steam_api.SteamApiError as error:
        account.last_sync_error = error.message[:300]
        return (
            "PARTIAL",
            (
                "Se actualizó el perfil, pero Steam no devolvió el tiempo "
                "de juego. Reintentá más tarde."
            ),
            error.code,
        )

    account.last_sync_error = None
    if owned is None:
        _delete_cs2_stats(account)
        return (
            "PARTIAL",
            (
                "La biblioteca de Steam no es pública; el tiempo de "
                "juego de CS2 no está disponible."
            ),
            None,
        )

    games = owned.get("games") or []
    if games:
        _upsert_cs2_stats(account, games[0])
        return "OK", "Datos de Steam actualizados.", None
    _delete_cs2_stats(account)
    return "OK", "Steam no devolvió datos de CS2 para esta cuenta.", None


def _sync_failure(user, account, now, error):
    account.last_sync_at = now
    account.last_sync_status = "ERROR"
    account.last_sync_error = error.message[:300]
    db.session.commit()
    return _sync_response(
        user,
        status="ERROR",
        message=(
            "No pudimos consultar Steam. Revisá la configuración y "
            "reintentá más tarde."
        ),
        error_code=error.code,
    )


def _sync_account_or_raise(user):
    account = user.steam_account
    if account is None:
        raise ApiError("No Steam account is linked", status_code=404)
    if not is_configured():
        raise ApiError(
            "Steam integration is not configured", status_code=503
        )
    return account


def sync_account(user):
    """Sincroniza perfil y tiempo de juego respetando el intervalo mínimo."""
    account = _sync_account_or_raise(user)

    now = utcnow()
    _interval, retry_after = _sync_interval_state(account, now)
    if retry_after is not None:
        return _sync_response(
            user,
            status="SKIPPED",
            message="La sincronización se hizo recientemente.",
            retry_after_seconds=retry_after,
        )

    try:
        summary = steam_api.fetch_player_summaries(account.steam_id)
        if summary is None:
            raise steam_api.SteamApiError(
                "Steam did not return a player summary", code="not_found"
            )
        _apply_summary(account, summary)
        status, message, error_code = _owned_games_outcome(account)
    except steam_api.SteamApiError as error:
        return _sync_failure(user, account, now, error)

    account.last_sync_at = now
    account.last_sync_status = status
    db.session.commit()
    return _sync_response(
        user,
        status=status,
        message=message,
        error_code=error_code,
    )


def _next_sync_at(account, interval):
    if account is None:
        return None
    last_sync_at = as_utc(account.last_sync_at)
    if last_sync_at is None:
        return None
    return last_sync_at + timedelta(seconds=interval)


def _can_sync(owner, next_sync_at, now):
    if not owner or not is_configured():
        return False
    return next_sync_at is None or now >= next_sync_at


def _sync_schedule(account, owner, interval, now):
    next_sync_at = _next_sync_at(account, interval)
    return _can_sync(owner, next_sync_at, now), next_sync_at


def _public_sync_fields(section):
    section["sync"].pop("min_interval_seconds", None)
    section["sync"].pop("last_sync_error", None)
    section["sync"].pop("api_configured", None)


def build_steam_section(user, *, owner=False):
    account = user.steam_account
    section = serialize_steam_section(
        account, owner=owner, configured=is_configured()
    )
    interval = int(
        current_app.config.get("STEAM_SYNC_MIN_INTERVAL_SECONDS", 300)
    )
    can_sync, next_sync_at = _sync_schedule(account, owner, interval, utcnow())
    section["sync"].update(
        {
            "can_sync": can_sync,
            "next_sync_at": _iso(next_sync_at),
        }
    )
    if owner:
        section["sync"]["min_interval_seconds"] = interval
    else:
        _public_sync_fields(section)
    return section


def _sync_response(
    user, *, status, message, retry_after_seconds=None, error_code=None
):
    section = build_steam_section(user, owner=True)
    sync = dict(section["sync"])
    sync["status"] = status
    sync["message"] = message
    if retry_after_seconds is not None:
        sync["retry_after_seconds"] = retry_after_seconds
    if error_code is not None:
        sync["error_code"] = error_code
    return {"sync": sync, "steam": section}
