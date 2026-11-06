"""Acceso a la Steam Web API oficial.

Solo se usan endpoints documentados por Valve:

- `ISteamUser/GetPlayerSummaries/v2` (perfil público básico).
- `IPlayerService/GetOwnedGames/v1` (biblioteca y tiempo de juego).

La Web API de Steam **no** expone estadísticas por jugador ni historial de
partidas de Counter-Strike 2. Este módulo no inventa ni completa esos datos.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

STEAM_API_BASE_URL = "https://api.steampowered.com"
STEAM_PLAYER_SUMMARIES_URL = (
    f"{STEAM_API_BASE_URL}/ISteamUser/GetPlayerSummaries/v2/"
)
STEAM_OWNED_GAMES_URL = (
    f"{STEAM_API_BASE_URL}/IPlayerService/GetOwnedGames/v1/"
)
STEAM_CS2_APP_ID = 730


class SteamApiError(Exception):
    """Error controlado al consultar la Steam Web API."""

    def __init__(self, message, code="upstream_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def is_configured():
    return bool(str(current_app.config.get("STEAM_API_KEY", "")).strip())


def _api_key():
    key = str(current_app.config.get("STEAM_API_KEY", "")).strip()
    if not key:
        raise SteamApiError(
            "Steam Web API key is not configured", code="not_configured"
        )
    return key


def _get_json(url, params):
    query = urlencode(params)
    request = Request(
        f"{url}?{query}",
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "cs2-manager-steam/1.0",
        },
    )
    timeout = float(current_app.config.get("STEAM_API_TIMEOUT_SECONDS", 10))
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        if error.code == 403:
            raise SteamApiError(
                "Steam Web API rejected the configured key",
                code="forbidden",
            ) from error
        if error.code == 429:
            raise SteamApiError(
                "Steam Web API rate limit reached", code="rate_limited"
            ) from error
        raise SteamApiError(
            f"Steam Web API returned HTTP {error.code}",
            code="http_error",
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise SteamApiError(
            "Steam Web API is unavailable", code="unavailable"
        ) from error

    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SteamApiError(
            "Steam Web API returned an invalid response",
            code="invalid_response",
        ) from error


def _parse_timestamp(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_text(value, max_length):
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] if text else None


def fetch_player_summaries(steam_id):
    """Devuelve el perfil público verificado de un SteamID64."""
    payload = _get_json(
        STEAM_PLAYER_SUMMARIES_URL,
        {"key": _api_key(), "steamids": str(steam_id)},
    )
    response = payload.get("response") if isinstance(payload, dict) else None
    players = response.get("players") if isinstance(response, dict) else None
    if not isinstance(players, list) or not players:
        raise SteamApiError(
            "Steam did not return a player summary", code="not_found"
        )

    player = players[0]
    if not isinstance(player, dict):
        raise SteamApiError(
            "Steam returned an invalid player summary",
            code="invalid_response",
        )

    returned_id = str(player.get("steamid", ""))
    if returned_id != str(steam_id):
        raise SteamApiError(
            "Steam returned a different player identity",
            code="invalid_response",
        )

    return {
        "steam_id": returned_id,
        "persona_name": _clean_text(player.get("personaname"), 100),
        "profile_url": _clean_text(player.get("profileurl"), 500),
        "avatar_url": _clean_text(player.get("avatar"), 500),
        "avatar_medium_url": _clean_text(player.get("avatarmedium"), 500),
        "avatar_full_url": _clean_text(player.get("avatarfull"), 500),
        "persona_state": player.get("personastate")
        if isinstance(player.get("personastate"), int)
        else None,
        "community_visibility_state": player.get(
            "communityvisibilitystate"
        )
        if isinstance(player.get("communityvisibilitystate"), int)
        else None,
        "profile_created_at": _parse_timestamp(player.get("timecreated")),
        "last_logoff_at": _parse_timestamp(player.get("lastlogoff")),
    }


def fetch_owned_games(steam_id, app_id=STEAM_CS2_APP_ID):
    """Devuelve la biblioteca pública del jugador o `None` si es privada.

    `GetOwnedGames` responde `{"response": {}}` cuando el perfil o la
    biblioteca no son públicos. Eso no se interpreta como "no posee el juego".
    """
    payload = _get_json(
        STEAM_OWNED_GAMES_URL,
        {
            "key": _api_key(),
            "steamid": str(steam_id),
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "appids_filter[0]": int(app_id),
        },
    )
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        raise SteamApiError(
            "Steam returned an invalid owned games response",
            code="invalid_response",
        )
    if "games" not in response:
        return None

    games = response.get("games")
    if not isinstance(games, list):
        raise SteamApiError(
            "Steam returned an invalid owned games list",
            code="invalid_response",
        )

    normalized = []
    for game in games:
        if not isinstance(game, dict):
            continue
        try:
            game_app_id = int(game.get("appid"))
        except (TypeError, ValueError):
            continue
        if game_app_id != int(app_id):
            continue
        normalized.append(
            {
                "app_id": game_app_id,
                "name": _clean_text(game.get("name"), 200),
                "playtime_forever_minutes": _non_negative_int(
                    game.get("playtime_forever")
                ),
                "playtime_two_weeks_minutes": _non_negative_int(
                    game.get("playtime_2weeks")
                ),
                "last_played": _parse_timestamp(game.get("last_played")),
                "img_icon_url": _clean_text(game.get("img_icon_url"), 100),
            }
        )

    return {
        "game_count": _non_negative_int(response.get("game_count")),
        "games": normalized,
    }


def _non_negative_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
