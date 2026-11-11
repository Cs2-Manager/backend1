"""Lógica de FACEIT: descubrimiento, vinculación, sincronización y consultas.

Principios:

- La identidad FACEIT se descubre desde el SteamID64 verificado del backend o
  se verifica con FACEIT Connect. Nunca se confía en un `player_id` enviado
  por el frontend para determinar propiedad.
- La sincronización es incremental e idempotente: las partidas se identifican
  por `(account_id, faceit_match_id)` y se actualizan, no se duplican.
- Un lease en `faceit_sync_states` evita sincronizaciones simultáneas del
  mismo jugador, incluso con varios procesos.
- Ante errores temporales se aplica backoff exponencial acotado.
- Si FACEIT no entrega una métrica, se guarda `None`. No se completa con cero.
- El ELO histórico solo contiene snapshots reales observados desde la primera
  sincronización.
"""

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ApiError
from app.extensions import db
from app.models.faceit import (
    FACEIT_GAME_ID,
    FaceitAccount,
    FaceitEloSnapshot,
    FaceitMapStats,
    FaceitMatch,
    FaceitMatchPlayerStats,
    FaceitOAuthRequest,
    FaceitPlayerStats,
    FaceitSyncState,
)
from app.models.steam import SteamAccount
from app.serializers.faceit import (
    NO_ACCOUNT_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    OAUTH_NOT_CONFIGURED_MESSAGE,
    serialize_faceit_match,
    serialize_faceit_section,
)
from app.services import faceit_api
from app.utils.time_utils import as_utc, utcnow

BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
MATCH_HISTORY_LIMIT = 200
ELO_HISTORY_LIMIT = 200


def _config(name, default=None):
    return current_app.config.get(name, default)


def _int_config(name, default):
    try:
        return int(_config(name, default))
    except (TypeError, ValueError):
        return default


def _truncate(value, limit=300):
    text = str(value) if value is not None else ""
    return text[:limit] or None


def _enabled():
    return bool(_config("FACEIT_ENABLED", True))


def _configured():
    return faceit_api.is_configured()


def _oauth_configured():
    return faceit_api.oauth_configured()


def _fernet():
    secret = str(
        _config("FACEIT_SECRET_KEY")
        or _config("SECRET_KEY")
        or ""
    )
    if not secret:
        raise RuntimeError("FACEIT_SECRET_KEY is not configured")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(value):
    return _fernet().encrypt(str(value).encode("utf-8")).decode("ascii")


def _decrypt(value):
    try:
        return _fernet().decrypt(str(value).encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def _sha256(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _steam_id_for(user):
    account = (
        db.session.query(SteamAccount).filter_by(user_id=user.id).first()
    )
    return account.steam_id if account is not None else None


def get_account(user):
    if user is None:
        return None
    return (
        db.session.query(FaceitAccount)
        .filter_by(user_id=user.id)
        .first()
    )


def _ensure_sync_state(account, *, commit=False):
    if account.sync_state is not None:
        return account.sync_state
    state = FaceitSyncState(account_id=account.id, status="NEVER")
    db.session.add(state)
    account.sync_state = state
    if commit:
        db.session.commit()
    return state


def _account_by_player_id(player_id):
    return (
        db.session.query(FaceitAccount)
        .filter_by(faceit_player_id=str(player_id))
        .first()
    )


def _min_interval():
    return max(0, _int_config("FACEIT_SYNC_MIN_INTERVAL_SECONDS", 300))


def oauth_request_ttl():
    return max(60, _int_config("FACEIT_OAUTH_REQUEST_TTL_SECONDS", 600))


def _sync_interval():
    return max(60, _int_config("FACEIT_SYNC_INTERVAL_SECONDS", 1800))


def _can_sync(account):
    if account is None or not account.sync_enabled:
        return False
    if not _enabled() or not _configured():
        return False
    state = account.sync_state
    now = utcnow()
    if state is not None:
        lease = as_utc(state.lease_until)
        if lease is not None and lease > now:
            return False
        next_at = as_utc(state.next_sync_at)
        if next_at is not None and next_at > now:
            return False
        last = as_utc(state.last_success_at)
        if last is not None and (now - last).total_seconds() < _min_interval():
            return False
    return True


def build_section(user, *, owner=False, recent_limit=10):
    account = get_account(user)
    configured = _configured()
    enabled = _enabled()
    oauth_ready = _oauth_configured()
    if account is None:
        return serialize_faceit_section(
            None,
            owner=owner,
            configured=configured,
            enabled=enabled,
            oauth_configured=oauth_ready,
            min_interval=_min_interval(),
            can_sync=False,
        )

    matches = (
        db.session.query(FaceitMatch)
        .filter_by(account_id=account.id)
        .order_by(
            FaceitMatch.played_at.desc().nullslast(),
            FaceitMatch.id.desc(),
        )
        .limit(MATCH_HISTORY_LIMIT)
        .all()
    )
    map_stats = (
        db.session.query(FaceitMapStats)
        .filter_by(account_id=account.id)
        .order_by(FaceitMapStats.map_name)
        .all()
    )
    elo_history = (
        db.session.query(FaceitEloSnapshot)
        .filter_by(account_id=account.id)
        .order_by(FaceitEloSnapshot.captured_at.asc())
        .limit(ELO_HISTORY_LIMIT)
        .all()
    )
    return serialize_faceit_section(
        account,
        owner=owner,
        configured=configured,
        enabled=enabled,
        oauth_configured=oauth_ready,
        min_interval=_min_interval(),
        can_sync=owner and _can_sync(account),
        matches=matches,
        map_stats=map_stats,
        elo_history=elo_history,
        recent_limit=recent_limit,
        history_total=len(matches),
    )


def status_payload(user):
    return {
        "faceit": build_section(user, owner=True),
        "configuration": {
            "api_configured": _configured(),
            "oauth_configured": _oauth_configured(),
            "enabled": _enabled(),
            "sync_interval_seconds": _sync_interval(),
            "sync_min_interval_seconds": _min_interval(),
            "history_days": max(
                1, _int_config("FACEIT_HISTORY_DAYS", 30)
            ),
        },
    }


def discover(user):
    if not _enabled():
        raise ApiError(
            "La integración con FACEIT está deshabilitada.", status_code=503
        )
    if not _configured():
        raise ApiError(NOT_CONFIGURED_MESSAGE, status_code=503)
    steam_id = _steam_id_for(user)
    if not steam_id:
        raise ApiError(
            "Vinculá tu cuenta de Steam antes de descubrir FACEIT.",
            status_code=409,
        )
    try:
        player = faceit_api.fetch_player_by_steam_id(steam_id)
    except faceit_api.FaceitApiError as error:
        if error.code == "not_found":
            return {
                "found": False,
                "message": (
                    "No encontramos una cuenta FACEIT asociada a tu SteamID. "
                    "Podés verificarla con FACEIT Connect si tu cuenta existe."
                ),
                "player": None,
                "claimed": False,
                "linked": False,
            }
        raise _api_error_from_upstream(error)

    existing = _account_by_player_id(player["player_id"])
    claimed = existing is not None and existing.user_id != user.id
    linked = existing is not None and existing.user_id == user.id
    message = None
    if claimed:
        message = (
            "La cuenta FACEIT encontrada ya está vinculada a otro usuario. "
            "No se muestra información de ese vínculo."
        )
    return {
        "found": True,
        "message": message,
        "player": player,
        "claimed": claimed,
        "linked": linked,
    }


def link_discovered(user, player_id=None):
    if not _enabled() or not _configured():
        raise ApiError(NOT_CONFIGURED_MESSAGE, status_code=503)
    steam_id = _steam_id_for(user)
    if not steam_id:
        raise ApiError(
            "Vinculá tu cuenta de Steam antes de vincular FACEIT.",
            status_code=409,
        )
    try:
        player = faceit_api.fetch_player_by_steam_id(steam_id)
    except faceit_api.FaceitApiError as error:
        if error.code == "not_found":
            raise ApiError(
                "No encontramos una cuenta FACEIT para tu SteamID.",
                status_code=404,
            ) from error
        raise _api_error_from_upstream(error) from error

    if player_id and str(player_id) != str(player["player_id"]):
        raise ApiError(
            "La cuenta FACEIT no coincide con tu SteamID verificado.",
            status_code=400,
        )

    existing = _account_by_player_id(player["player_id"])
    if existing is not None and existing.user_id != user.id:
        raise ApiError(
            "La cuenta FACEIT ya está vinculada a otro usuario.",
            status_code=409,
        )
    current = get_account(user)
    if current is not None and current.faceit_player_id != player["player_id"]:
        raise ApiError(
            "Ya tenés otra cuenta FACEIT vinculada. Desvinculala primero.",
            status_code=409,
        )

    account = existing or current
    if account is None:
        account = FaceitAccount(user_id=user.id)
        db.session.add(account)
    _apply_player(account, player)
    account.link_status = "DISCOVERED"
    account.verification_source = "STEAM_DISCOVERY"
    account.verified_at = None
    account.steam_id = steam_id
    account.sync_enabled = True
    account.updated_at = utcnow()
    db.session.flush()
    _ensure_sync_state(account)
    db.session.commit()
    return build_section(user, owner=True)


def start_oauth(user):
    if not _enabled():
        raise ApiError(
            "La integración con FACEIT está deshabilitada.", status_code=503
        )
    if not _oauth_configured():
        raise ApiError(OAUTH_NOT_CONFIGURED_MESSAGE, status_code=503)

    now = utcnow()
    ttl = oauth_request_ttl()
    # Limpieza acotada de solicitudes vencidas del propio usuario.
    db.session.query(FaceitOAuthRequest).filter(
        FaceitOAuthRequest.user_id == user.id,
        FaceitOAuthRequest.expires_at < now,
    ).delete(synchronize_session=False)

    state = secrets.token_urlsafe(48)
    verifier, challenge = faceit_api.build_pkce_pair()
    request = FaceitOAuthRequest(
        state_hash=_sha256(state),
        code_verifier_encrypted=_encrypt(verifier),
        user_id=user.id,
        return_to="/profile",
        expires_at=now + timedelta(seconds=ttl),
    )
    db.session.add(request)
    db.session.commit()

    params = {
        "client_id": _config("FACEIT_OAUTH_CLIENT_ID"),
        "redirect_uri": _config("FACEIT_OAUTH_REDIRECT_URI"),
        "response_type": "code",
        # FACEIT exige declarar explícitamente si debe redirigir la ventana
        # abierta. El frontend usa una redirección completa (location.assign),
        # no un popup, pero FACEIT rechaza la solicitud con HTTP 400 si el
        # parámetro falta.
        "redirect_popup": "true",
        "scope": _config(
            "FACEIT_OAUTH_SCOPES", "openid profile membership"
        ),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    base = str(
        _config("FACEIT_OAUTH_AUTHORIZE_URL", "https://accounts.faceit.com")
    )
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode(params)}"


def _frontend_redirect(*, result, reason=None):
    current_app.logger.warning(
        "faceit_oauth_callback http=302 category=%s", reason or result
    )
    base = str(
        _config("FACEIT_PUBLIC_BASE_URL", "http://localhost")
    ).rstrip("/")
    params = {"faceit": result}
    if reason:
        params["reason"] = reason
    return f"{base}/profile?{urlencode(params)}"


def process_oauth_callback(args):
    """Procesa el callback OAuth. Siempre redirige, nunca filtra secretos."""
    try:
        return _process_oauth_callback(args)
    except SQLAlchemyError:
        db.session.rollback()
        return _frontend_redirect(result="error", reason="database_error")
    except Exception:
        # No registrar la excepción: puede incluir parámetros SQL o secretos.
        db.session.rollback()
        return _frontend_redirect(result="error", reason="internal_error")


def _finish_oauth(request, *, reason=None):
    # La vinculación y el consumo se confirman juntos. Los fallos terminales
    # también consumen el state: un code enviado a FACEIT no debe reintentarse.
    request.consumed_at = utcnow()
    db.session.commit()
    return _frontend_redirect(
        result="error" if reason else "linked", reason=reason
    )


def _process_oauth_callback(args):
    if not _enabled() or not _oauth_configured():
        return _frontend_redirect(result="error", reason="not_configured")

    state = (args.get("state") or "").strip()
    code = (args.get("code") or "").strip()
    if not state or (not code and not args.get("error")):
        return _frontend_redirect(result="error", reason="invalid_state")

    now = utcnow()
    request = (
        db.session.query(FaceitOAuthRequest)
        .filter_by(state_hash=_sha256(state))
        # PostgreSQL serializa callbacks del mismo state, incluso entre
        # procesos. El bloqueo dura hasta el resultado terminal/rollback.
        .populate_existing()
        .with_for_update()
        .first()
    )
    if (
        request is None
        or request.consumed_at is not None
        or as_utc(request.expires_at) <= utcnow()
    ):
        db.session.rollback()
        return _frontend_redirect(result="error", reason="invalid_state")

    if args.get("error"):
        return _finish_oauth(request, reason="access_denied")

    verifier = _decrypt(request.code_verifier_encrypted)
    if not verifier:
        db.session.rollback()
        return _frontend_redirect(result="error", reason="invalid_state")

    try:
        token = faceit_api.exchange_oauth_code(code, verifier)
    except faceit_api.FaceitApiError as error:
        if error.code == "not_configured":
            db.session.rollback()
            return _frontend_redirect(result="error", reason="not_configured")
        return _finish_oauth(request, reason="exchange_failed")

    try:
        userinfo = faceit_api.fetch_oauth_userinfo(token["access_token"])
    except faceit_api.FaceitApiError:
        return _finish_oauth(request, reason="userinfo_failed")

    # FACEIT Connect devuelve el identificador como `guid`; se aceptan también
    # las variantes documentadas por otros proveedores/versiones.
    player_id = str(
        userinfo.get("guid")
        or userinfo.get("sub")
        or userinfo.get("player_id")
        or userinfo.get("user_id")
        or ""
    ).strip()
    if not player_id:
        return _finish_oauth(request, reason="userinfo_failed")

    try:
        player = faceit_api.fetch_player(player_id)
    except faceit_api.FaceitApiError:
        # FACEIT Connect ya verificó la identidad; si Data API no responde se
        # conserva el identificador y los datos básicos del userinfo.
        player = {
            "player_id": player_id,
            "nickname": userinfo.get("nickname") or userinfo.get("name"),
            "avatar_url": userinfo.get("picture"),
            "cover_image_url": None,
            "country": userinfo.get("country"),
            "region": None,
            "steam_id": userinfo.get("steam_id_64"),
            "steam_nickname": None,
            "faceit_url": None,
            "elo": None,
            "skill_level": None,
        }

    if str(player.get("player_id") or "") != player_id:
        return _finish_oauth(request, reason="userinfo_failed")

    existing = _account_by_player_id(player_id)
    if existing is not None and existing.user_id != request.user_id:
        return _finish_oauth(request, reason="account_conflict")
    current = get_account(request.user)
    if current is not None and current.faceit_player_id != player_id:
        return _finish_oauth(request, reason="already_linked")

    account = existing or current
    if account is None:
        account = FaceitAccount(user_id=request.user_id)
        db.session.add(account)
    _apply_player(account, player)
    account.link_status = "VERIFIED"
    account.verification_source = "OAUTH2"
    account.verified_at = now
    account.steam_id = player.get("steam_id") or _steam_id_for(request.user)
    account.sync_enabled = True
    account.updated_at = now
    db.session.flush()
    _ensure_sync_state(account)
    return _finish_oauth(request)


def _apply_player(account, player):
    if player.get("player_id"):
        account.faceit_player_id = str(player["player_id"])
    if player.get("nickname") is not None:
        account.nickname = player["nickname"]
    if player.get("avatar_url") is not None:
        account.avatar_url = player["avatar_url"]
    if player.get("cover_image_url") is not None:
        account.cover_image_url = player["cover_image_url"]
    if player.get("country") is not None:
        account.country = player["country"]
    if player.get("region") is not None:
        account.region = player["region"]
    if player.get("steam_id") is not None:
        account.steam_id = player["steam_id"]
    if player.get("steam_nickname") is not None:
        account.steam_nickname = player["steam_nickname"]
    if player.get("faceit_url") is not None:
        account.faceit_url = player["faceit_url"]
    if player.get("elo") is not None:
        account.elo = player["elo"]
    if player.get("skill_level") is not None:
        account.skill_level = player["skill_level"]


def unlink(user):
    account = get_account(user)
    if account is None:
        raise ApiError("No hay una cuenta FACEIT vinculada.", status_code=404)
    db.session.delete(account)
    db.session.commit()
    return build_section(user, owner=True)


def _api_error_from_upstream(error):
    if error.code == "not_configured":
        return ApiError(NOT_CONFIGURED_MESSAGE, status_code=503)
    if error.code == "rate_limited":
        return ApiError(
            "FACEIT limitó temporalmente las solicitudes. Intentá más tarde.",
            status_code=429,
        )
    if error.code == "not_found":
        return ApiError("FACEIT no encontró el recurso.", status_code=404)
    if error.code in ("unauthorized", "forbidden"):
        return ApiError(
            "FACEIT rechazó las credenciales configuradas.", status_code=502
        )
    return ApiError(
        "FACEIT no está disponible en este momento.", status_code=502
    )


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------


def _acquire_lease(account, *, force):
    state = _ensure_sync_state(account)
    db.session.flush()
    # En PostgreSQL el FOR UPDATE serializa la adquisición entre procesos.
    locked = (
        db.session.query(FaceitSyncState)
        .filter_by(id=state.id)
        .with_for_update()
        .first()
    )
    if locked is None:
        return state, "SKIPPED", "No se pudo bloquear el estado de sincronización."
    now = utcnow()
    lease = as_utc(locked.lease_until)
    if lease is not None and lease > now:
        return locked, "SKIPPED", "Ya hay una sincronización en curso."

    last = as_utc(locked.last_success_at)
    if (
        not force
        and last is not None
        and (now - last).total_seconds() < _min_interval()
    ):
        next_at = last + timedelta(seconds=_min_interval())
        locked.next_sync_at = next_at
        db.session.commit()
        return (
            locked,
            "SKIPPED",
            "Esperá al intervalo mínimo entre sincronizaciones.",
        )

    locked.lease_until = now + timedelta(
        seconds=max(60, _int_config("FACEIT_SYNC_LEASE_SECONDS", 600))
    )
    locked.last_attempt_at = now
    db.session.commit()
    return locked, None, None


def _release_lease(state):
    if state is None:
        return
    state.lease_until = None
    db.session.add(state)


def _history_from(account):
    state = account.sync_state
    last = as_utc(state.last_success_at) if state else None
    now = utcnow()
    if last is not None:
        return max(last - timedelta(hours=1), now - timedelta(days=3650))
    return now - timedelta(
        days=max(1, _int_config("FACEIT_HISTORY_DAYS", 30))
    )


def _upsert_match(account, data):
    match = (
        db.session.query(FaceitMatch)
        .filter_by(
            account_id=account.id,
            faceit_match_id=data["faceit_match_id"],
        )
        .first()
    )
    created = match is None
    if match is None:
        match = FaceitMatch(
            account_id=account.id,
            faceit_match_id=data["faceit_match_id"],
        )
        db.session.add(match)

    for field in (
        "played_at",
        "game_mode",
        "map_name",
        "region",
        "competition_name",
        "result",
        "team_score",
        "opponent_score",
        "score",
        "player_team_name",
        "opponent_team_name",
        "faceit_url",
    ):
        value = data.get(field)
        if value is not None:
            setattr(match, field, value)
    if data.get("status") == "OK" or match.status is None:
        match.status = data.get("status") or "PARTIAL"
    match.fetched_at = utcnow()
    match.updated_at = utcnow()
    db.session.flush()

    stats_fields = (
        "kills",
        "deaths",
        "assists",
        "kd",
        "kr",
        "adr",
        "headshot_percentage",
        "mvps",
        "rounds_played",
    )
    has_stats = any(data.get(field) is not None for field in stats_fields)
    if has_stats:
        stats = match.player_stats
        if stats is None:
            stats = FaceitMatchPlayerStats(match_id=match.id)
            db.session.add(stats)
            match.player_stats = stats
        for field in stats_fields:
            value = data.get(field)
            if value is not None:
                setattr(stats, field, value)
        stats.fetched_at = utcnow()
        if match.status == "PARTIAL":
            match.status = "OK"
    return match, created


def _update_player_stats(account, lifetime):
    stats = account.stats
    if stats is None:
        stats = FaceitPlayerStats(account_id=account.id)
        db.session.add(stats)
        account.stats = stats
    for field, value in lifetime.items():
        if value is not None:
            setattr(stats, field, value)
    stats.game_id = FACEIT_GAME_ID
    stats.fetched_at = utcnow()


def _replace_map_segments(account, rows):
    existing = {
        row.map_name: row
        for row in db.session.query(FaceitMapStats)
        .filter_by(account_id=account.id)
        .all()
    }
    for data in rows:
        row = existing.pop(data["map_name"], None)
        if row is None:
            row = FaceitMapStats(
                account_id=account.id, map_name=data["map_name"]
            )
            db.session.add(row)
        for field in (
            "matches_played",
            "wins",
            "losses",
            "win_rate",
            "kills",
            "deaths",
            "assists",
            "kd",
            "adr",
            "headshot_percentage",
        ):
            value = data.get(field)
            if value is not None:
                setattr(row, field, value)
        row.source = "VERIFIED_FACEIT"
        row.calculated_from = "FACEIT_SEGMENT"
        row.updated_at = utcnow()
    # Las filas que FACEIT ya no reporta se conservan si tienen historial
    # local; solo se eliminan las que nunca tuvieron datos.
    for row in existing.values():
        if row.matches_played is None and row.wins is None:
            db.session.delete(row)


def _aggregate_maps_from_matches(account):
    rows = (
        db.session.query(FaceitMatch)
        .filter(
            FaceitMatch.account_id == account.id,
            FaceitMatch.map_name.isnot(None),
        )
        .all()
    )
    grouped = {}
    for match in rows:
        bucket = grouped.setdefault(
            match.map_name,
            {
                "matches_played": 0,
                "wins": 0,
                "losses": 0,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "kd_values": [],
                "adr_values": [],
                "hs_values": [],
            },
        )
        bucket["matches_played"] += 1
        if match.result == "WIN":
            bucket["wins"] += 1
        elif match.result == "LOSS":
            bucket["losses"] += 1
        stats = match.player_stats
        if stats is None:
            continue
        if stats.kills is not None:
            bucket["kills"] += stats.kills
        if stats.deaths is not None:
            bucket["deaths"] += stats.deaths
        if stats.assists is not None:
            bucket["assists"] += stats.assists
        if stats.kd is not None:
            bucket["kd_values"].append(stats.kd)
        if stats.adr is not None:
            bucket["adr_values"].append(stats.adr)
        if stats.headshot_percentage is not None:
            bucket["hs_values"].append(stats.headshot_percentage)

    def average(values):
        return round(sum(values) / len(values), 2) if values else None

    result = []
    for map_name, bucket in grouped.items():
        played = bucket["matches_played"]
        result.append(
            {
                "map_name": map_name,
                "matches_played": played,
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "win_rate": round(bucket["wins"] * 100 / played, 1)
                if played
                else None,
                "kills": bucket["kills"] or None,
                "deaths": bucket["deaths"] or None,
                "assists": bucket["assists"] or None,
                "kd": round(bucket["kills"] / bucket["deaths"], 2)
                if bucket["deaths"]
                else average(bucket["kd_values"]),
                "adr": average(bucket["adr_values"]),
                "headshot_percentage": average(bucket["hs_values"]),
            }
        )
    return result


def _replace_aggregated_maps(account, rows):
    existing = {
        row.map_name: row
        for row in db.session.query(FaceitMapStats)
        .filter_by(account_id=account.id)
        .all()
    }
    for data in rows:
        row = existing.pop(data["map_name"], None)
        if row is None:
            row = FaceitMapStats(
                account_id=account.id, map_name=data["map_name"]
            )
            db.session.add(row)
        for field in (
            "matches_played",
            "wins",
            "losses",
            "win_rate",
            "kills",
            "deaths",
            "assists",
            "kd",
            "adr",
            "headshot_percentage",
        ):
            setattr(row, field, data.get(field))
        row.source = "VERIFIED_FACEIT"
        row.calculated_from = "MATCH_AGGREGATE"
        row.updated_at = utcnow()
    for row in existing.values():
        if row.calculated_from == "MATCH_AGGREGATE":
            db.session.delete(row)


def _record_elo(account):
    if account.elo is None:
        return False
    last = (
        db.session.query(FaceitEloSnapshot)
        .filter_by(account_id=account.id)
        .order_by(FaceitEloSnapshot.captured_at.desc())
        .first()
    )
    if (
        last is not None
        and last.elo == account.elo
        and last.skill_level == account.skill_level
    ):
        return False
    now = utcnow()
    db.session.add(
        FaceitEloSnapshot(
            account_id=account.id,
            elo=account.elo,
            skill_level=account.skill_level,
            captured_at=now,
            source="VERIFIED_FACEIT",
        )
    )
    return True


def _collect_game_stats(account):
    rows = []
    from_ms = int(_history_from(account).timestamp() * 1000)
    limit = max(1, min(_int_config("FACEIT_HISTORY_LIMIT", 100), 100))
    pages = max(1, _int_config("FACEIT_HISTORY_MAX_PAGES", 3))
    for page in range(pages):
        payload = faceit_api.fetch_player_game_stats(
            account.faceit_player_id,
            offset=page * limit,
            limit=limit,
            from_ms=from_ms,
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        items = items if isinstance(items, list) else []
        for item in items:
            normalized = faceit_api.normalize_game_stat_item(
                item, account.faceit_player_id
            )
            if normalized is not None:
                rows.append(normalized)
        if len(items) < limit:
            break
    return rows


def _collect_history(account):
    rows = []
    from_ts = int(_history_from(account).timestamp())
    limit = max(1, min(_int_config("FACEIT_HISTORY_LIMIT", 100), 100))
    pages = max(1, _int_config("FACEIT_HISTORY_MAX_PAGES", 3))
    for page in range(pages):
        payload = faceit_api.fetch_player_history(
            account.faceit_player_id,
            offset=page * limit,
            limit=limit,
            from_ts=from_ts,
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        items = items if isinstance(items, list) else []
        for item in items:
            normalized = faceit_api.normalize_history_item(
                item, account.faceit_player_id
            )
            if normalized is not None:
                rows.append(normalized)
        if len(items) < limit:
            break
    return rows


def sync(user, *, force=False):
    if not _enabled():
        raise ApiError(
            "La integración con FACEIT está deshabilitada.", status_code=503
        )
    if not _configured():
        raise ApiError(NOT_CONFIGURED_MESSAGE, status_code=503)
    account = get_account(user)
    if account is None:
        raise ApiError(
            "No hay una cuenta FACEIT vinculada.", status_code=404
        )
    if not account.sync_enabled:
        raise ApiError(
            "La sincronización automática está desactivada para esta cuenta.",
            status_code=409,
        )

    state, skipped, message = _acquire_lease(account, force=force)
    if skipped:
        db.session.refresh(account)
        section = build_section(user, owner=True)
        return {
            "status": skipped,
            "message": message,
            "faceit": section,
            "sync": section["sync"],
        }

    partial_reasons = []
    created = 0
    updated = 0
    elo_recorded = False
    try:
        player = faceit_api.fetch_player(account.faceit_player_id)
        _apply_player(account, player)

        try:
            stats_payload = faceit_api.fetch_player_stats(
                account.faceit_player_id
            )
            lifetime = faceit_api.normalize_lifetime(stats_payload)
            _update_player_stats(account, lifetime)
            segments = faceit_api.normalize_map_segments(stats_payload)
        except faceit_api.FaceitApiError:
            segments = []
            partial_reasons.append("estadísticas generales")

        try:
            game_rows = _collect_game_stats(account)
        except faceit_api.FaceitApiError:
            game_rows = []
            partial_reasons.append("estadísticas por partida")

        try:
            history_rows = _collect_history(account)
        except faceit_api.FaceitApiError:
            history_rows = []
            partial_reasons.append("historial de partidas")

        known = {row["faceit_match_id"] for row in game_rows}
        merged = list(game_rows)
        for row in history_rows:
            if row["faceit_match_id"] not in known:
                merged.append(row)

        for row in merged:
            _match, was_created = _upsert_match(account, row)
            created += int(was_created)
            updated += int(not was_created)

        if segments:
            _replace_map_segments(account, segments)
        else:
            _replace_aggregated_maps(
                account, _aggregate_maps_from_matches(account)
            )

        elo_recorded = _record_elo(account)
        if not merged:
            partial_reasons.append("partidas disponibles")

        now = utcnow()
        state.status = "PARTIAL" if partial_reasons else "OK"
        state.last_success_at = now
        state.next_sync_at = now + timedelta(seconds=_sync_interval())
        state.consecutive_failures = 0
        state.last_error = (
            "Datos parciales: " + ", ".join(partial_reasons) + "."
            if partial_reasons
            else None
        )
        _release_lease(state)
        db.session.commit()
    except faceit_api.FaceitApiError as error:
        db.session.rollback()
        state = (
            db.session.query(FaceitSyncState)
            .filter_by(account_id=account.id)
            .first()
        )
        if state is not None:
            now = utcnow()
            state.consecutive_failures = (state.consecutive_failures or 0) + 1
            delay = min(
                BACKOFF_BASE_SECONDS * (2 ** (state.consecutive_failures - 1)),
                BACKOFF_MAX_SECONDS,
            )
            state.status = (
                "NOT_CONFIGURED"
                if error.code == "not_configured"
                else "ERROR"
            )
            state.last_error = _truncate(error.message)
            state.next_sync_at = now + timedelta(seconds=delay)
            _release_lease(state)
            db.session.commit()
        section = build_section(user, owner=True)
        return {
            "status": section["sync"]["status"],
            "message": section["sync"].get("last_error")
            or "No se pudo sincronizar con FACEIT.",
            "faceit": section,
            "sync": section["sync"],
        }
    except Exception:
        db.session.rollback()
        state = (
            db.session.query(FaceitSyncState)
            .filter_by(account_id=account.id)
            .first()
        )
        if state is not None:
            now = utcnow()
            state.status = "ERROR"
            state.consecutive_failures = (state.consecutive_failures or 0) + 1
            state.last_error = "Error interno durante la sincronización."
            state.next_sync_at = now + timedelta(seconds=BACKOFF_BASE_SECONDS)
            _release_lease(state)
            db.session.commit()
        current_app.logger.exception("FACEIT sync failed")
        section = build_section(user, owner=True)
        return {
            "status": "ERROR",
            "message": "No se pudo sincronizar con FACEIT.",
            "faceit": section,
            "sync": section["sync"],
        }

    section = build_section(user, owner=True)
    return {
        "status": section["sync"]["status"],
        "message": section["sync"].get("last_error")
        or "Sincronización de FACEIT completada.",
        "created_matches": created,
        "updated_matches": updated,
        "elo_snapshot": elo_recorded,
        "partial_reasons": partial_reasons,
        "faceit": section,
        "sync": section["sync"],
    }


def sync_due_accounts(limit=None):
    """Sincroniza cuentas cuyo `next_sync_at` ya venció.

    Pensado para el worker existente. No crea schedulers adicionales.
    """
    if not _enabled() or not _configured():
        return {"synced": 0, "skipped": 0, "errors": 0, "status": "NOT_CONFIGURED"}
    batch = limit or max(1, _int_config("FACEIT_SYNC_BATCH_SIZE", 5))
    now = utcnow()
    accounts = (
        db.session.query(FaceitAccount)
        .join(FaceitSyncState, FaceitSyncState.account_id == FaceitAccount.id)
        .filter(
            FaceitAccount.sync_enabled.is_(True),
            FaceitSyncState.next_sync_at.isnot(None),
            FaceitSyncState.next_sync_at <= now,
        )
        .order_by(FaceitSyncState.next_sync_at.asc())
        .limit(batch)
        .all()
    )
    # Las cuentas recién vinculadas no tienen `next_sync_at`: se incluyen una
    # vez para registrar su primer snapshot real.
    pending = (
        db.session.query(FaceitAccount)
        .join(FaceitSyncState, FaceitSyncState.account_id == FaceitAccount.id)
        .filter(
            FaceitAccount.sync_enabled.is_(True),
            FaceitSyncState.next_sync_at.is_(None),
            FaceitSyncState.last_attempt_at.is_(None),
        )
        .limit(max(0, batch - len(accounts)))
        .all()
    )
    accounts.extend(pending)

    result = {"synced": 0, "skipped": 0, "errors": 0, "status": "OK"}
    for account in accounts:
        try:
            outcome = sync(account.user, force=True)
        except Exception:  # noqa: BLE001 - el worker debe seguir vivo
            db.session.rollback()
            current_app.logger.exception("FACEIT automatic sync failed")
            result["errors"] += 1
            continue
        if outcome["status"] == "SKIPPED":
            result["skipped"] += 1
        elif outcome["status"] in ("OK", "PARTIAL"):
            result["synced"] += 1
        else:
            result["errors"] += 1
    if result["errors"]:
        result["status"] = "PARTIAL" if result["synced"] else "ERROR"
    return result


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def _require_account(user):
    account = get_account(user)
    if account is None:
        raise ApiError(
            "No hay una cuenta FACEIT vinculada.", status_code=404
        )
    return account


def list_matches(user, *, limit=25, offset=0, map_name=None, result=None):
    account = _require_account(user)
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    query = db.session.query(FaceitMatch).filter_by(account_id=account.id)
    if map_name:
        query = query.filter(FaceitMatch.map_name == map_name)
    if result:
        query = query.filter(FaceitMatch.result == result.upper())
    total = query.count()
    rows = (
        query.order_by(
            FaceitMatch.played_at.desc().nullslast(),
            FaceitMatch.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "matches": [serialize_faceit_match(row) for row in rows],
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {"map": map_name, "result": result},
    }


def get_match(user, match_id, *, refresh=False):
    account = _require_account(user)
    match = (
        db.session.query(FaceitMatch)
        .filter_by(account_id=account.id, id=match_id)
        .first()
    )
    if match is None:
        raise ApiError("Partida FACEIT no encontrada.", status_code=404)
    if refresh and _configured():
        _refresh_match(account, match)
    return serialize_faceit_match(match, owner=True)


def _refresh_match(account, match):
    try:
        detail = faceit_api.fetch_match(match.faceit_match_id)
        normalized = faceit_api.normalize_match_detail(
            detail, account.faceit_player_id
        )
        for field, value in normalized.items():
            if value is not None:
                setattr(match, field, value)
        try:
            stats_payload = faceit_api.fetch_match_stats(
                match.faceit_match_id
            )
            stats = faceit_api.normalize_match_stats(
                stats_payload, account.faceit_player_id
            )
            if stats.get("map_name"):
                match.map_name = stats["map_name"]
            if any(
                stats.get(field) is not None
                for field in (
                    "kills",
                    "deaths",
                    "assists",
                    "kd",
                    "adr",
                    "headshot_percentage",
                    "mvps",
                )
            ):
                _upsert_match(
                    account,
                    {
                        "faceit_match_id": match.faceit_match_id,
                        "status": "OK",
                        **stats,
                    },
                )
        except faceit_api.FaceitApiError:
            pass
        match.fetched_at = utcnow()
        match.updated_at = utcnow()
        db.session.commit()
    except faceit_api.FaceitApiError:
        db.session.rollback()


def list_maps(user):
    account = _require_account(user)
    rows = (
        db.session.query(FaceitMapStats)
        .filter_by(account_id=account.id)
        .order_by(FaceitMapStats.map_name)
        .all()
    )
    from app.serializers.faceit import serialize_faceit_map

    return {"maps": [serialize_faceit_map(row) for row in rows]}


def list_elo_history(user):
    account = _require_account(user)
    rows = (
        db.session.query(FaceitEloSnapshot)
        .filter_by(account_id=account.id)
        .order_by(FaceitEloSnapshot.captured_at.asc())
        .limit(ELO_HISTORY_LIMIT)
        .all()
    )
    from app.serializers.faceit import serialize_elo_snapshot

    return {
        "snapshots": [serialize_elo_snapshot(row) for row in rows],
        "count": len(rows),
        "source": "VERIFIED_FACEIT",
        "message": (
            "El historial de ELO comienza en el primer snapshot real "
            "registrado por CS2 Manager."
        )
        if rows
        else "Todavía no hay snapshots reales de ELO.",
    }


def stats_payload(user):
    return {
        "faceit": build_section(user, owner=True),
        "stats": build_section(user, owner=True)["stats"],
    }
