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


def _to_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


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
    query = urlencode(params or {}, doseq=True)
    full_url = f"{url}?{query}" if query else url
    cache_key = f"{method}:{full_url}"
    if cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    global _BLOCKED_UNTIL
    now = time.monotonic()
    if now < _BLOCKED_UNTIL:
        raise FaceitApiError(
            "FACEIT rate limit is active; retry later",
            code="rate_limited",
            retry_after=max(1, int(_BLOCKED_UNTIL - now)),
        )

    max_retries = (
        _int_config("FACEIT_API_MAX_RETRIES", 2)
        if retries is None
        else int(retries)
    )
    max_retries = max(0, max_retries)
    base_delay = max(
        0.0, _float_config("FACEIT_API_BACKOFF_BASE_SECONDS", 0.5)
    )
    request_timeout = timeout or _float_config(
        "FACEIT_API_TIMEOUT_SECONDS", 10
    )
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "cs2-manager-faceit/1.0",
        **(headers or {}),
    }

    last_error = None
    for attempt in range(max_retries + 1):
        request = Request(
            full_url,
            method=method,
            headers=request_headers,
            data=body,
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
                if oauth_stage:
                    current_app.logger.warning(
                        "faceit_oauth_%s http=%s category=ok",
                        oauth_stage, response.status,
                    )
            payload = _decode_json(raw)
            if cache:
                _cache_set(cache_key, payload)
            return payload
        except HTTPError as error:
            status = error.code
            retry_after = _retry_after_seconds(error.headers)
            if oauth_stage:
                category = "http_error"
                try:
                    payload = json.loads(error.read(16384))
                    candidate = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(candidate, str) and candidate in OAUTH_ERROR_CATEGORIES:
                        category = candidate
                except (ValueError, OSError):
                    pass
                if (
                    category == "http_error"
                    and oauth_stage == "token"
                    and status == 401
                    and str((error.headers or {}).get("WWW-Authenticate", ""))
                    .lower().startswith("basic")
                ):
                    # FACEIT también puede rechazar Basic con HTML, sin el
                    # campo JSON `error`. No inventar un invalid_client literal.
                    category = "client_authentication_failed"
                current_app.logger.warning(
                    "faceit_oauth_%s http=%s category=%s",
                    oauth_stage, status, category,
                )
                if category != "http_error":
                    raise FaceitApiError(
                        "FACEIT rejected the OAuth request",
                        code=category, status=status,
                    ) from None
            if status == 401:
                raise FaceitApiError(
                    "FACEIT rejected the configured credentials",
                    code="unauthorized",
                    status=status,
                ) from error
            if status == 403:
                raise FaceitApiError(
                    "FACEIT denied access to this resource",
                    code="forbidden",
                    status=status,
                ) from error
            if status == 404:
                raise FaceitApiError(
                    "FACEIT resource not found",
                    code="not_found",
                    status=status,
                ) from error
            if status == 429:
                delay = retry_after or 30
                _BLOCKED_UNTIL = time.monotonic() + min(delay, 120)
                last_error = FaceitApiError(
                    "FACEIT rate limit reached",
                    code="rate_limited",
                    status=status,
                    retry_after=delay,
                )
                if attempt < max_retries:
                    time.sleep(min(base_delay * (2**attempt), 5))
                    continue
                raise last_error from error
            if status in (500, 502, 503, 504):
                last_error = FaceitApiError(
                    "FACEIT is temporarily unavailable",
                    code="unavailable",
                    status=status,
                    retry_after=retry_after,
                )
                if attempt < max_retries:
                    time.sleep(
                        min(
                            retry_after
                            or base_delay * (2**attempt),
                            5,
                        )
                    )
                    continue
                raise last_error from error
            raise FaceitApiError(
                f"FACEIT returned HTTP {status}",
                code="http_error",
                status=status,
                retry_after=retry_after,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            if oauth_stage:
                current_app.logger.warning(
                    "faceit_oauth_%s http=none category=unavailable", oauth_stage
                )
            last_error = FaceitApiError(
                "FACEIT is unavailable", code="unavailable"
            )
            if attempt < max_retries:
                time.sleep(min(base_delay * (2**attempt), 5))
                continue
            raise last_error from error

    raise last_error or FaceitApiError("FACEIT request failed")


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
    return [item for item in items if isinstance(item, dict)]


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


def normalize_player(payload):
    games = payload.get("games") if isinstance(payload, dict) else None
    cs2 = games.get(FACEIT_GAME_ID) if isinstance(games, dict) else None
    cs2 = cs2 if isinstance(cs2, dict) else {}
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
        "verified": bool(payload.get("verified")) if isinstance(
            payload, dict
        ) else False,
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


def normalize_map_segments(payload):
    """Extrae los segmentos `type=Map` del endpoint de estadísticas."""
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        return []
    rows = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type") or "").strip().lower()
        if segment_type not in ("map", "maps"):
            continue
        label = _clean(segment.get("label"), 80)
        if not label:
            continue
        stats = segment.get("stats")
        stats = stats if isinstance(stats, dict) else {}
        rows.append(
            {
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
        )
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


def normalize_history_item(item, player_id):
    """Normaliza un elemento de `/players/{id}/history` (sin estadísticas)."""
    if not isinstance(item, dict):
        return None
    match_id = _clean(_first(item, "match_id", "Match Id"), 64)
    if not match_id:
        return None

    teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
    player_team_key = None
    for key, team in teams.items():
        roster = team.get("players") if isinstance(team, dict) else None
        if not isinstance(roster, list):
            continue
        if any(
            str(player.get("player_id")) == str(player_id)
            for player in roster
            if isinstance(player, dict)
        ):
            player_team_key = key
            break

    player_team = (
        teams.get(player_team_key)
        if player_team_key is not None
        else None
    )
    opponent_key = next(
        (key for key in teams if key != player_team_key), None
    )
    opponent_team = teams.get(opponent_key) if opponent_key else None
    results = item.get("results") if isinstance(item.get("results"), dict) else {}
    score = results.get("score") if isinstance(results.get("score"), dict) else {}
    player_score = score.get(player_team_key) if player_team_key else None
    opponent_score = score.get(opponent_key) if opponent_key else None
    winner = results.get("winner")
    if winner is not None and player_team_key is not None:
        result = "WIN" if str(winner) == str(player_team_key) else "LOSS"
    else:
        result = None

    played_at = _epoch_seconds(
        _first(item, "finished_at", "started_at")
    )
    return {
        "faceit_match_id": match_id,
        "played_at": played_at,
        "game_mode": _clean(_first(item, "game_mode", "match_type"), 60),
        "map_name": None,
        "region": _clean(item.get("region"), 20),
        "competition_name": _clean(item.get("competition_name"), 160),
        "result": result,
        "team_score": _to_int(player_score),
        "opponent_score": _to_int(opponent_score),
        "score": (
            f"{player_score} / {opponent_score}"
            if player_score is not None and opponent_score is not None
            else None
        ),
        "player_team_name": _clean(
            player_team.get("nickname") if isinstance(player_team, dict) else None,
            120,
        ),
        "opponent_team_name": _clean(
            opponent_team.get("nickname")
            if isinstance(opponent_team, dict)
            else None,
            120,
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
    teams = payload.get("teams") if isinstance(payload.get("teams"), dict) else {}
    player_team_key = None
    for key, team in teams.items():
        roster = team.get("roster") if isinstance(team, dict) else None
        if not isinstance(roster, list):
            continue
        if any(
            str(member.get("player_id")) == str(player_id)
            for member in roster
            if isinstance(member, dict)
        ):
            player_team_key = key
            break
    opponent_key = next(
        (key for key in teams if key != player_team_key), None
    )
    player_team = teams.get(player_team_key) if player_team_key else None
    opponent_team = teams.get(opponent_key) if opponent_key else None
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    score = results.get("score") if isinstance(results.get("score"), dict) else {}
    winner = results.get("winner")
    return {
        "game_mode": _clean(_first(payload, "game_mode", "game"), 60),
        "region": _clean(payload.get("region"), 20),
        "competition_name": _clean(payload.get("competition_name"), 160),
        "played_at": _epoch_seconds(
            _first(payload, "finished_at", "started_at")
        ),
        "player_team_name": _clean(
            player_team.get("name") if isinstance(player_team, dict) else None,
            120,
        ),
        "opponent_team_name": _clean(
            opponent_team.get("name")
            if isinstance(opponent_team, dict)
            else None,
            120,
        ),
        "team_score": _to_int(
            score.get(player_team_key) if player_team_key else None
        ),
        "opponent_score": _to_int(
            score.get(opponent_key) if opponent_key else None
        ),
        "result": (
            "WIN"
            if winner is not None
            and player_team_key is not None
            and str(winner) == str(player_team_key)
            else (
                "LOSS"
                if winner is not None and player_team_key is not None
                else None
            )
        ),
        "faceit_url": _clean(payload.get("faceit_url"), 500),
    }


def normalize_match_stats(payload, player_id):
    """Extrae mapa y estadísticas individuales de `/matches/{id}/stats`."""
    rounds = payload.get("rounds") if isinstance(payload, dict) else None
    if not isinstance(rounds, list):
        return {}
    map_name = None
    totals = {
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "mvps": 0,
        "rounds_played": 0,
    }
    adr_values = []
    headshot_values = []
    found = False
    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        round_stats = round_data.get("round_stats")
        if isinstance(round_stats, dict) and map_name is None:
            map_name = _clean(_first(round_stats, "Map", "Map Name"), 80)
        teams = round_data.get("teams")
        if not isinstance(teams, list):
            continue
        for team in teams:
            players = team.get("players") if isinstance(team, dict) else None
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                if str(player.get("player_id")) != str(player_id):
                    continue
                found = True
                stats = player.get("player_stats")
                stats = stats if isinstance(stats, dict) else {}
                for key, field in (
                    ("Kills", "kills"),
                    ("Deaths", "deaths"),
                    ("Assists", "assists"),
                    ("MVPs", "mvps"),
                ):
                    number = _to_int(stats.get(key))
                    if number is not None:
                        totals[field] += number
                adr = _to_float(stats.get("ADR"))
                if adr is not None:
                    adr_values.append(adr)
                hs = _to_percentage(
                    _first(stats, "Headshots %", "Headshot %")
                )
                if hs is not None:
                    headshot_values.append(hs)
                totals["rounds_played"] += 1
    if not found:
        return {"map_name": map_name} if map_name else {}
    kills = totals["kills"]
    deaths = totals["deaths"]
    return {
        "map_name": map_name,
        "kills": kills,
        "deaths": deaths,
        "assists": totals["assists"],
        "kd": round(kills / deaths, 2) if deaths else None,
        "adr": round(sum(adr_values) / len(adr_values), 1)
        if adr_values
        else None,
        "headshot_percentage": round(
            sum(headshot_values) / len(headshot_values), 1
        )
        if headshot_values
        else None,
        "mvps": totals["mvps"],
        "rounds_played": totals["rounds_played"] or None,
    }


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


def exchange_oauth_code(code, code_verifier):
    """Canjea el authorization code. Nunca se reintenta (código de un uso)."""
    client_id = str(_config("FACEIT_OAUTH_CLIENT_ID", "")).strip()
    client_secret = str(
        _config("FACEIT_OAUTH_CLIENT_SECRET", "")
    ).strip()
    redirect_uri = str(_config("FACEIT_OAUTH_REDIRECT_URI", "")).strip()
    if not (client_id and client_secret and redirect_uri):
        raise FaceitApiError(
            "FACEIT Connect is not configured", code="not_configured"
        )

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
