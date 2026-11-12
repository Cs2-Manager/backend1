"""Cliente centralizado de FACEIT Data API v4 y FACEIT Connect.

Características deliberadas:

- Solo endpoints oficiales (`https://open.faceit.com/data/v4`). Nunca scraping.
- La API key y el client secret se leen de la configuración del backend y
  jamás se incluyen en respuestas, excepciones o logs.
- Reintentos con backoff limitado únicamente para operaciones idempotentes
  (GET). El canje del código OAuth no se reintenta: el código es de un solo uso.
- Respeto de `Retry-After` y de un bloqueo local tras un 429 para no generar
  solicitudes masivas.
- Caché en memoria de vida corta para evitar consultas redundantes durante una
  misma sincronización.
- Normalización defensiva: cada métrica ausente queda en `None`, nunca en 0.

La API real no garantiza todas las claves de estadísticas. Por eso las
funciones `normalize_*` devuelven diccionarios con campos opcionales.
"""

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

FACEIT_GAME_ID = "cs2"
FACEIT_API_BASE_URL = "https://open.faceit.com/data/v4"
FACEIT_WEB_BASE_URL = "https://www.faceit.com/en/cs2/room"

# Caché y bloqueo locales del proceso. Son cotas de seguridad, no la fuente de
# verdad: cada worker/backend tiene la suya y FACEIT sigue siendo el límite
# último.
_CACHE = {}
_BLOCKED_UNTIL = 0.0

# Solo se conserva la categoría estándar, nunca error_description ni cuerpos
# del proveedor (pueden contener códigos, credenciales o tokens).
OAUTH_ERROR_CATEGORIES = frozenset({
    "invalid_grant", "invalid_client", "invalid_redirect_uri",
    "invalid_request", "invalid_scope", "unauthorized_client",
    "unsupported_grant_type", "access_denied", "invalid_pkce",
    "pkce_verification_failed",
})


class FaceitApiError(Exception):
    """Error controlado al consultar FACEIT."""

    def __init__(
        self,
        message,
        code="upstream_error",
        *,
        status=None,
        retry_after=None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.retry_after = retry_after


def _config(name, default=None):
    return current_app.config.get(name, default)


def _int_config(name, default):
    try:
        return int(_config(name, default))
    except (TypeError, ValueError):
        return default


def _float_config(name, default):
    try:
        return float(_config(name, default))
    except (TypeError, ValueError):
        return default


def is_configured():
    return bool(str(_config("FACEIT_API_KEY", "")).strip())


def oauth_configured():
    return all(
        str(_config(name, "")).strip()
        for name in (
            "FACEIT_OAUTH_CLIENT_ID",
            "FACEIT_OAUTH_CLIENT_SECRET",
            "FACEIT_OAUTH_REDIRECT_URI",
        )
    )


def _api_key():
    key = str(_config("FACEIT_API_KEY", "")).strip()
    if not key:
        raise FaceitApiError(
            "FACEIT API key is not configured", code="not_configured"
        )
    return key


def _base_url():
    return str(
        _config("FACEIT_API_BASE_URL", FACEIT_API_BASE_URL)
    ).rstrip("/")


def _truncate(value, limit=300):
    text = str(value) if value is not None else ""
    return text[:limit] or None


def _clean(value, limit):
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _is_missing(value):
    return value is None or isinstance(value, bool)


def _strip_numeric(text, percent):
    cleaned = text.strip().replace(",", "")
    return cleaned.replace("%", "") if percent else cleaned


def _numeric_text(value, *, percent):
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _strip_numeric(str(value), percent)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    number = _numeric_text(value, percent=False)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _to_float(value):
    return _numeric_text(value, percent=True)


def _to_percentage(value):
    number = _to_float(value)
    if number is None:
        return None
    return round(number, 2)


def _first(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _epoch_seconds(value):
    number = _to_int(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc)


def _epoch_milliseconds(value):
    number = _to_int(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000, tz=timezone.utc)


def _cache_get(key):
    ttl = _int_config("FACEIT_CACHE_TTL_SECONDS", 60)
    if ttl <= 0:
        return None
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if expires_at <= time.monotonic():
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key, payload):
    ttl = _int_config("FACEIT_CACHE_TTL_SECONDS", 60)
    if ttl <= 0:
        return
    # Cota simple para que un proceso de larga vida no crezca sin límite.
    if len(_CACHE) > 512:
        _CACHE.clear()
    _CACHE[key] = (time.monotonic() + ttl, payload)


def clear_cache():
    _CACHE.clear()


def _decode_json(raw):
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise FaceitApiError(
            "FACEIT returned an invalid JSON response",
            code="invalid_response",
        ) from error


def _full_url(url, params):
    query = urlencode(params or {}, doseq=True)
    return f"{url}?{query}" if query else url


def _request_settings(retries, timeout):
    max_retries = (
        _int_config("FACEIT_API_MAX_RETRIES", 2)
        if retries is None
        else int(retries)
    )
    return {
        "max_retries": max(0, max_retries),
        "base_delay": max(
            0.0, _float_config("FACEIT_API_BACKOFF_BASE_SECONDS", 0.5)
        ),
        "timeout": timeout or _float_config(
            "FACEIT_API_TIMEOUT_SECONDS", 10
        ),
    }


def _request_headers(headers):
    return {
        "Accept": "application/json",
        "User-Agent": "cs2-manager-faceit/1.0",
        **(headers or {}),
    }


def _ensure_not_blocked():
    now = time.monotonic()
    if now < _BLOCKED_UNTIL:
        raise FaceitApiError(
            "FACEIT rate limit is active; retry later",
            code="rate_limited",
            retry_after=max(1, int(_BLOCKED_UNTIL - now)),
        )


def _blocked_for(delay):
    global _BLOCKED_UNTIL
    _BLOCKED_UNTIL = time.monotonic() + min(delay, 120)


def _read_payload(response, oauth_stage):
    raw = response.read().decode("utf-8", errors="replace")
    if oauth_stage:
        current_app.logger.warning(
            "faceit_oauth_%s http=%s category=ok",
            oauth_stage, response.status,
        )
    return _decode_json(raw)


def _oauth_candidate(payload):
    candidate = payload.get("error") if isinstance(payload, dict) else None
    return candidate if isinstance(candidate, str) else None


def _basic_auth_rejected(error, status, oauth_stage):
    if oauth_stage != "token" or status != 401:
        return False
    header = str((error.headers or {}).get("WWW-Authenticate", ""))
    return header.lower().startswith("basic")


def _oauth_error_category(error, status, oauth_stage):
    category = "http_error"
    try:
        payload = json.loads(error.read(16384))
    except (ValueError, OSError):
        payload = None
    candidate = _oauth_candidate(payload)
    if candidate in OAUTH_ERROR_CATEGORIES:
        category = candidate
    elif _basic_auth_rejected(error, status, oauth_stage):
        category = "client_authentication_failed"
    return category


def _handle_oauth_http_error(error, status, oauth_stage):
    category = _oauth_error_category(error, status, oauth_stage)
    current_app.logger.warning(
        "faceit_oauth_%s http=%s category=%s",
        oauth_stage, status, category,
    )
    if category != "http_error":
        raise FaceitApiError(
            "FACEIT rejected the OAuth request",
            code=category, status=status,
        ) from None


_HTTP_ERROR_CODES = {
    401: ("FACEIT rejected the configured credentials", "unauthorized"),
    403: ("FACEIT denied access to this resource", "forbidden"),
    404: ("FACEIT resource not found", "not_found"),
}


def _raise_status_error(error, status, retry_after):
    message, code = _HTTP_ERROR_CODES.get(
        status, (f"FACEIT returned HTTP {status}", "http_error")
    )
    raise FaceitApiError(
        message, code=code, status=status, retry_after=retry_after
    ) from error


def _maybe_retry(error, last_error, wait, can_retry):
    if can_retry:
        time.sleep(min(wait, 5))
        return True
    raise last_error from error


def _rate_limit_error(status, retry_after):
    delay = retry_after or 30
    _blocked_for(delay)
    return FaceitApiError(
        "FACEIT rate limit reached",
        code="rate_limited",
        status=status,
        retry_after=delay,
    )


def _unavailable_error(status, retry_after):
    return FaceitApiError(
        "FACEIT is temporarily unavailable",
        code="unavailable",
        status=status,
        retry_after=retry_after,
    )


def _handle_http_error(error, status, retry_after, context):
    """Reintenta si corresponde; en caso contrario lanza el error final."""
    if context["oauth_stage"]:
        _handle_oauth_http_error(error, status, context["oauth_stage"])
    can_retry = context["attempt"] < context["max_retries"]
    if status == 429:
        wait = context["base_delay"] * (2 ** context["attempt"])
        return _maybe_retry(
            error, _rate_limit_error(status, retry_after), wait, can_retry
        )
    if status in (500, 502, 503, 504):
        wait = retry_after or context["base_delay"] * (2 ** context["attempt"])
        return _maybe_retry(
            error, _unavailable_error(status, retry_after), wait, can_retry
        )
    _raise_status_error(error, status, retry_after)


def _log_unavailable(oauth_stage):
    if oauth_stage:
        current_app.logger.warning(
            "faceit_oauth_%s http=none category=unavailable", oauth_stage
        )


def _perform_request(request, settings, context):
    """Devuelve (payload, False) o (None, True) si hay que reintentar."""
    try:
        with urlopen(request, timeout=settings["timeout"]) as response:  # noqa: S310
            payload = _read_payload(response, context["oauth_stage"])
    except HTTPError as error:
        return None, _handle_http_error(
            error,
            error.code,
            _retry_after_seconds(error.headers),
            context,
        )
    except (URLError, TimeoutError, OSError) as error:
        _log_unavailable(context["oauth_stage"])
        last_error = FaceitApiError(
            "FACEIT is unavailable", code="unavailable"
        )
        wait = context["base_delay"] * (2 ** context["attempt"])
        can_retry = context["attempt"] < context["max_retries"]
        return None, _maybe_retry(error, last_error, wait, can_retry)
    if context["cache"]:
        _cache_set(context["cache_key"], payload)
    return payload, False


def _request_json(
    url,
    *,
    params=None,
    headers=None,
    method="GET",
    body=None,
    timeout=None,
    retries=None,
    cache=True,
    oauth_stage=None,
):
    full_url = _full_url(url, params)
    cache_key = f"{method}:{full_url}"
    if cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    _ensure_not_blocked()

    settings = _request_settings(retries, timeout)
    request_headers = _request_headers(headers)
    for attempt in range(settings["max_retries"] + 1):
        context = {
            "attempt": attempt,
            "max_retries": settings["max_retries"],
            "base_delay": settings["base_delay"],
            "oauth_stage": oauth_stage,
            "cache": cache,
            "cache_key": cache_key,
        }
        request = Request(
            full_url,
            method=method,
            headers=request_headers,
            data=body,
        )
        payload, retry = _perform_request(request, settings, context)
        if not retry:
            return payload
    raise FaceitApiError("FACEIT request failed")


def _retry_after_seconds(headers):
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    number = _to_int(raw)
    if number is None or number < 0:
        return None
    return min(number, 120)


def _get(path, params=None, *, retries=None, cache=True):
    key = _api_key()
    return _request_json(
        f"{_base_url()}{path}",
        params=params,
        headers={"Authorization": f"Bearer {key}"},
        retries=retries,
        cache=cache,
    )


def _dict_items(items):
    return [item for item in items if isinstance(item, dict)]


def _items(payload):
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned an invalid collection",
            code="invalid_response",
        )
    items = payload.get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise FaceitApiError(
            "FACEIT returned an invalid item list",
            code="invalid_response",
        )
    return _dict_items(items)


# ---------------------------------------------------------------------------
# Data API: jugadores
# ---------------------------------------------------------------------------


def fetch_player_by_steam_id(steam_id):
    """Busca el jugador FACEIT asociado a un SteamID64 verificado."""
    payload = _get(
        "/players",
        {"game": FACEIT_GAME_ID, "game_player_id": str(steam_id)},
    )
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned an invalid player", code="invalid_response"
        )
    player = normalize_player(payload)
    if not player["player_id"]:
        raise FaceitApiError(
            "FACEIT returned a player without an identifier",
            code="invalid_response",
        )
    return player


def fetch_player(player_id):
    payload = _get(f"/players/{player_id}")
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned an invalid player", code="invalid_response"
        )
    player = normalize_player(payload)
    if not player["player_id"]:
        raise FaceitApiError(
            "FACEIT returned a player without an identifier",
            code="invalid_response",
        )
    return player


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _cs2_game(payload):
    games = _as_dict(payload.get("games")) if isinstance(payload, dict) else {}
    return _as_dict(games.get(FACEIT_GAME_ID))


def _verified_flag(payload):
    return bool(payload.get("verified")) if isinstance(payload, dict) else False


def normalize_player(payload):
    cs2 = _cs2_game(payload)
    player_id = _clean(
        _first(payload, "player_id", "id", "user_id"), 64
    )
    steam_id = _clean(
        _first(payload, "steam_id_64", "new_steam_id")
        or cs2.get("game_player_id"),
        20,
    )
    return {
        "player_id": player_id,
        "nickname": _clean(payload.get("nickname"), 100),
        "avatar_url": _clean(payload.get("avatar"), 500),
        "cover_image_url": _clean(
            _first(payload, "cover_image", "cover_featured_image"), 500
        ),
        "country": _clean(payload.get("country"), 8),
        "region": _clean(cs2.get("region"), 20),
        "steam_id": steam_id,
        "steam_nickname": _clean(payload.get("steam_nickname"), 100),
        "faceit_url": _clean(payload.get("faceit_url"), 500),
        "elo": _to_int(cs2.get("faceit_elo")),
        "skill_level": _to_int(cs2.get("skill_level")),
        "game_player_name": _clean(cs2.get("game_player_name"), 100),
        "verified": _verified_flag(payload),
    }


# ---------------------------------------------------------------------------
# Data API: estadísticas
# ---------------------------------------------------------------------------


def fetch_player_stats(player_id, game_id=FACEIT_GAME_ID):
    payload = _get(f"/players/{player_id}/stats/{game_id}")
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned invalid player statistics",
            code="invalid_response",
        )
    return payload


def fetch_player_game_stats(
    player_id,
    *,
    offset=0,
    limit=100,
    from_ms=None,
    game_id=FACEIT_GAME_ID,
):
    params = {
        "offset": max(0, min(int(offset), 200)),
        "limit": max(1, min(int(limit), 100)),
    }
    if from_ms is not None:
        params["from"] = int(from_ms)
    payload = _get(
        f"/players/{player_id}/games/{game_id}/stats", params
    )
    return payload


def fetch_player_history(
    player_id,
    *,
    offset=0,
    limit=20,
    from_ts=None,
    to_ts=None,
    game_id=FACEIT_GAME_ID,
):
    params = {
        "game": game_id,
        "offset": max(0, min(int(offset), 1000)),
        "limit": max(1, min(int(limit), 100)),
    }
    if from_ts is not None:
        params["from"] = int(from_ts)
    if to_ts is not None:
        params["to"] = int(to_ts)
    return _get(f"/players/{player_id}/history", params)


def fetch_match(match_id):
    payload = _get(f"/matches/{match_id}")
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned invalid match details",
            code="invalid_response",
        )
    return payload


def fetch_match_stats(match_id):
    payload = _get(f"/matches/{match_id}/stats")
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT returned invalid match statistics",
            code="invalid_response",
        )
    return payload


def normalize_lifetime(payload):
    """Normaliza el bloque `lifetime` de `/players/{id}/stats/cs2`."""
    lifetime = payload.get("lifetime") if isinstance(payload, dict) else None
    lifetime = lifetime if isinstance(lifetime, dict) else {}
    return {
        "matches_played": _to_int(
            _first(lifetime, "Total Matches", "Matches")
        ),
        "wins": _to_int(_first(lifetime, "Total Wins", "Wins")),
        "losses": _to_int(_first(lifetime, "Total Losses", "Losses")),
        "win_rate": _to_percentage(
            _first(lifetime, "Win Rate %", "Win Rate")
        ),
        "kills": _to_int(_first(lifetime, "Total Kills", "Kills")),
        "deaths": _to_int(_first(lifetime, "Total Deaths", "Deaths")),
        "assists": _to_int(_first(lifetime, "Total Assists", "Assists")),
        "kd": _to_float(_first(lifetime, "K/D Ratio", "KD Ratio")),
        "kr": _to_float(_first(lifetime, "K/R Ratio", "KR Ratio")),
        "headshots": _to_int(
            _first(lifetime, "Total Headshots", "Headshots")
        ),
        "headshot_percentage": _to_percentage(
            _first(lifetime, "Headshots %", "Headshot %")
        ),
        "adr": _to_float(_first(lifetime, "ADR", "Average Damage")),
        "mvps": _to_int(_first(lifetime, "MVPs", "Total MVPs")),
        "triple_kills": _to_int(
            _first(lifetime, "Triple Kills", "Total Triple Kills")
        ),
        "quadruple_kills": _to_int(
            _first(
                lifetime,
                "Quadro Kills",
                "Quadruple Kills",
                "Total Quadro Kills",
            )
        ),
        "penta_kills": _to_int(
            _first(lifetime, "Penta Kills", "Total Penta Kills")
        ),
        "rounds_played": _to_int(
            _first(lifetime, "Total Rounds", "Rounds")
        ),
        "total_damage": _to_int(
            _first(lifetime, "Total Damage", "Damage")
        ),
    }


def _segments(payload):
    segments = payload.get("segments") if isinstance(payload, dict) else None
    return segments if isinstance(segments, list) else []


def _map_segment_row(segment):
    segment_type = str(segment.get("type") or "").strip().lower()
    if segment_type not in ("map", "maps"):
        return None
    label = _clean(segment.get("label"), 80)
    if not label:
        return None
    stats = segment.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    return {
        "map_name": label,
        "matches_played": _to_int(
            _first(stats, "Matches", "Total Matches")
        ),
        "wins": _to_int(_first(stats, "Wins", "Total Wins")),
        "losses": _to_int(
            _first(stats, "Losses", "Total Losses")
        ),
        "win_rate": _to_percentage(
            _first(stats, "Win Rate %", "Win Rate")
        ),
        "kills": _to_int(
            _first(stats, "Kills", "Total Kills")
        ),
        "deaths": _to_int(
            _first(stats, "Deaths", "Total Deaths")
        ),
        "assists": _to_int(
            _first(stats, "Assists", "Total Assists")
        ),
        "kd": _to_float(
            _first(stats, "K/D Ratio", "KD Ratio")
        ),
        "adr": _to_float(_first(stats, "ADR")),
        "headshot_percentage": _to_percentage(
            _first(stats, "Headshots %", "Headshot %")
        ),
    }


def normalize_map_segments(payload):
    """Extrae los segmentos `type=Map` del endpoint de estadísticas."""
    rows = []
    for segment in _segments(payload):
        if not isinstance(segment, dict):
            continue
        row = _map_segment_row(segment)
        if row is not None:
            rows.append(row)
    return rows


def _parse_score(score):
    text = _clean(score, 40)
    if not text:
        return None, None
    parts = [part.strip() for part in text.replace(":", "/").split("/")]
    if len(parts) < 2:
        return None, None
    return _to_int(parts[0]), _to_int(parts[1])


def _normalize_result(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "win", "won", "victory", "true"):
        return "WIN"
    if text in ("0", "loss", "lost", "defeat", "false"):
        return "LOSS"
    if text in ("draw", "tie"):
        return "DRAW"
    return None


def normalize_game_stat_item(item, player_id):
    """Normaliza un elemento de `/players/{id}/games/cs2/stats`."""
    stats = item.get("stats") if isinstance(item, dict) else None
    stats = stats if isinstance(stats, dict) else {}
    match_id = _clean(
        _first(stats, "Match Id", "Match ID", "match_id"), 64
    )
    if not match_id:
        return None
    team_score, opponent_score = _parse_score(stats.get("Score"))
    return {
        "faceit_match_id": match_id,
        "played_at": _epoch_milliseconds(
            _first(stats, "Match Finished At", "Match Finished")
        ),
        "game_mode": _clean(
            _first(stats, "Game Mode", "Game Mode Name"), 60
        ),
        "map_name": _clean(_first(stats, "Map", "Map Name"), 80),
        "region": _clean(stats.get("Region"), 20),
        "competition_name": None,
        "result": _normalize_result(stats.get("Result")),
        "team_score": team_score,
        "opponent_score": opponent_score,
        "score": _clean(stats.get("Score"), 40),
        "player_team_name": None,
        "opponent_team_name": None,
        "faceit_url": _clean(item.get("faceit_url"), 500)
        or f"{FACEIT_WEB_BASE_URL}/{match_id}",
        "status": "OK",
        "kills": _to_int(stats.get("Kills")),
        "deaths": _to_int(stats.get("Deaths")),
        "assists": _to_int(stats.get("Assists")),
        "kd": _to_float(_first(stats, "K/D Ratio", "KD Ratio")),
        "kr": _to_float(_first(stats, "K/R Ratio", "KR Ratio")),
        "adr": _to_float(stats.get("ADR")),
        "headshot_percentage": _to_percentage(
            _first(stats, "Headshots %", "Headshot %")
        ),
        "mvps": _to_int(stats.get("MVPs")),
        "rounds_played": _to_int(
            _first(stats, "Rounds", "Total Rounds")
        ),
        "player_id": player_id,
    }


def _team_roster(team, roster_field):
    return team.get(roster_field) if isinstance(team, dict) else None


def _has_player(roster, player_id):
    return any(
        str(member.get("player_id")) == str(player_id)
        for member in roster
        if isinstance(member, dict)
    )


def _find_player_team_key(teams, player_id, roster_field):
    for key, team in teams.items():
        roster = _team_roster(team, roster_field)
        if isinstance(roster, list) and _has_player(roster, player_id):
            return key
    return None


def _team_keys(teams, player_id, roster_field):
    player_key = _find_player_team_key(teams, player_id, roster_field)
    opponent_key = next(
        (key for key in teams if key != player_key), None
    )
    return player_key, opponent_key


def _team_entry(teams, key):
    return teams.get(key) if key else None


def _team_name(team, field):
    if not isinstance(team, dict):
        return None
    return _clean(team.get(field), 120)


def _match_result(winner, player_key):
    if winner is None or player_key is None:
        return None
    return "WIN" if str(winner) == str(player_key) else "LOSS"


def _score_pair(score, player_key, opponent_key):
    return (
        score.get(player_key) if player_key else None,
        score.get(opponent_key) if opponent_key else None,
    )


def _history_score(player_score, opponent_score):
    if player_score is None or opponent_score is None:
        return None
    return f"{player_score} / {opponent_score}"


def normalize_history_item(item, player_id):
    """Normaliza un elemento de `/players/{id}/history` (sin estadísticas)."""
    if not isinstance(item, dict):
        return None
    match_id = _clean(_first(item, "match_id", "Match Id"), 64)
    if not match_id:
        return None

    teams = _as_dict(item.get("teams"))
    player_key, opponent_key = _team_keys(teams, player_id, "players")
    results = _as_dict(item.get("results"))
    score = _as_dict(results.get("score"))
    player_score, opponent_score = _score_pair(
        score, player_key, opponent_key
    )
    return {
        "faceit_match_id": match_id,
        "played_at": _epoch_seconds(
            _first(item, "finished_at", "started_at")
        ),
        "game_mode": _clean(_first(item, "game_mode", "match_type"), 60),
        "map_name": None,
        "region": _clean(item.get("region"), 20),
        "competition_name": _clean(item.get("competition_name"), 160),
        "result": _match_result(results.get("winner"), player_key),
        "team_score": _to_int(player_score),
        "opponent_score": _to_int(opponent_score),
        "score": _history_score(player_score, opponent_score),
        "player_team_name": _team_name(
            _team_entry(teams, player_key), "nickname"
        ),
        "opponent_team_name": _team_name(
            _team_entry(teams, opponent_key), "nickname"
        ),
        "faceit_url": _clean(item.get("faceit_url"), 500)
        or f"{FACEIT_WEB_BASE_URL}/{match_id}",
        "status": "PARTIAL",
        "player_id": player_id,
    }


def normalize_match_detail(payload, player_id):
    """Extrae mapa, equipos, marcador y URL de `/matches/{id}`."""
    if not isinstance(payload, dict):
        return {}
    teams = _as_dict(payload.get("teams"))
    player_key, opponent_key = _team_keys(teams, player_id, "roster")
    results = _as_dict(payload.get("results"))
    score = _as_dict(results.get("score"))
    player_score, opponent_score = _score_pair(
        score, player_key, opponent_key
    )
    return {
        "game_mode": _clean(_first(payload, "game_mode", "game"), 60),
        "region": _clean(payload.get("region"), 20),
        "competition_name": _clean(payload.get("competition_name"), 160),
        "played_at": _epoch_seconds(
            _first(payload, "finished_at", "started_at")
        ),
        "player_team_name": _team_name(
            _team_entry(teams, player_key), "name"
        ),
        "opponent_team_name": _team_name(
            _team_entry(teams, opponent_key), "name"
        ),
        "team_score": _to_int(player_score),
        "opponent_score": _to_int(opponent_score),
        "result": _match_result(results.get("winner"), player_key),
        "faceit_url": _clean(payload.get("faceit_url"), 500),
    }


_STAT_KEYS = (
    ("Kills", "kills"),
    ("Deaths", "deaths"),
    ("Assists", "assists"),
    ("MVPs", "mvps"),
)


def _empty_totals():
    return {
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "mvps": 0,
        "rounds_played": 0,
    }


def _round_map_name(round_data):
    round_stats = round_data.get("round_stats")
    if not isinstance(round_stats, dict):
        return None
    return _clean(_first(round_stats, "Map", "Map Name"), 80)


def _player_round_stats(player):
    stats = player.get("player_stats")
    return stats if isinstance(stats, dict) else {}


def _add_stats(stats, totals):
    for key, field in _STAT_KEYS:
        number = _to_int(stats.get(key))
        if number is not None:
            totals[field] += number


def _append_metric(values, value):
    if value is not None:
        values.append(value)


def _accumulate_player(player, player_id, totals, adr_values, headshot_values):
    """Suma las métricas del jugador solicitado. Devuelve si lo encontró."""
    if not isinstance(player, dict):
        return False
    if str(player.get("player_id")) != str(player_id):
        return False
    stats = _player_round_stats(player)
    _add_stats(stats, totals)
    _append_metric(adr_values, _to_float(stats.get("ADR")))
    _append_metric(
        headshot_values,
        _to_percentage(_first(stats, "Headshots %", "Headshot %")),
    )
    totals["rounds_played"] += 1
    return True


def _accumulate_team(team, player_id, totals, adr_values, headshot_values):
    players = team.get("players") if isinstance(team, dict) else None
    if not isinstance(players, list):
        return False
    found = False
    for player in players:
        found = _accumulate_player(
            player, player_id, totals, adr_values, headshot_values
        ) or found
    return found


def _accumulate_round(round_data, player_id, totals, adr_values, headshot_values):
    map_name = _round_map_name(round_data)
    teams = round_data.get("teams")
    found = False
    if isinstance(teams, list):
        for team in teams:
            found = _accumulate_team(
                team, player_id, totals, adr_values, headshot_values
            ) or found
    return map_name, found


def _collect_round_stats(rounds, player_id):
    totals = _empty_totals()
    adr_values = []
    headshot_values = []
    map_name = None
    found = False
    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        round_map, round_found = _accumulate_round(
            round_data, player_id, totals, adr_values, headshot_values
        )
        map_name = map_name or round_map
        found = round_found or found
    return map_name, found, totals, adr_values, headshot_values


def _mean(values, digits):
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _stats_payload(map_name, totals, adr_values, headshot_values):
    kills = totals["kills"]
    deaths = totals["deaths"]
    return {
        "map_name": map_name,
        "kills": kills,
        "deaths": deaths,
        "assists": totals["assists"],
        "kd": round(kills / deaths, 2) if deaths else None,
        "adr": _mean(adr_values, 1),
        "headshot_percentage": _mean(headshot_values, 1),
        "mvps": totals["mvps"],
        "rounds_played": totals["rounds_played"] or None,
    }


def normalize_match_stats(payload, player_id):
    """Extrae mapa y estadísticas individuales de `/matches/{id}/stats`."""
    rounds = payload.get("rounds") if isinstance(payload, dict) else None
    if not isinstance(rounds, list):
        return {}
    map_name, found, totals, adr_values, headshot_values = _collect_round_stats(
        rounds, player_id
    )
    if not found:
        return {"map_name": map_name} if map_name else {}
    return _stats_payload(map_name, totals, adr_values, headshot_values)


# ---------------------------------------------------------------------------
# FACEIT Connect (OAuth2 Authorization Code + PKCE)
# ---------------------------------------------------------------------------


def build_pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = (
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    )
    return verifier, challenge


def _require_oauth_config():
    client_id = str(_config("FACEIT_OAUTH_CLIENT_ID", "")).strip()
    client_secret = str(
        _config("FACEIT_OAUTH_CLIENT_SECRET", "")
    ).strip()
    redirect_uri = str(_config("FACEIT_OAUTH_REDIRECT_URI", "")).strip()
    if not all((client_id, client_secret, redirect_uri)):
        raise FaceitApiError(
            "FACEIT Connect is not configured", code="not_configured"
        )
    return client_id, client_secret, redirect_uri


def exchange_oauth_code(code, code_verifier):
    """Canjea el authorization code. Nunca se reintenta (código de un uso)."""
    client_id, client_secret, redirect_uri = _require_oauth_config()

    token_url = str(
        _config(
            "FACEIT_OAUTH_TOKEN_URL",
            "https://api.faceit.com/auth/v1/oauth/token",
        )
    )
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    payload = _request_json(
        token_url,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=body,
        timeout=_float_config("FACEIT_OAUTH_TIMEOUT_SECONDS", 10),
        retries=0,
        cache=False,
        oauth_stage="token",
    )
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise FaceitApiError(
            "FACEIT Connect did not return an access token",
            code="invalid_response",
        )
    return payload


def fetch_oauth_userinfo(access_token):
    url = str(
        _config(
            "FACEIT_OAUTH_USERINFO_URL",
            "https://api.faceit.com/auth/v1/resources/userinfo",
        )
    )
    payload = _request_json(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_float_config("FACEIT_OAUTH_TIMEOUT_SECONDS", 10),
        retries=0,
        cache=False,
        oauth_stage="userinfo",
    )
    if not isinstance(payload, dict):
        raise FaceitApiError(
            "FACEIT Connect returned invalid user information",
            code="invalid_response",
        )
    return payload
