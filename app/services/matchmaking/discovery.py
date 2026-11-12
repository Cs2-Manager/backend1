"""Descubrimiento de share codes con la API oficial de Valve.

Endpoint usado (el único documentado para este fin):

    GET https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/
        ?key=...&steamid=...&steamidkey=...&knowncode=CSGO-...

Devuelve **el siguiente** share code del historial del jugador. No existe un
endpoint oficial que devuelva todo el historial ni las estadísticas. El
recorrido se hace de a un código, avanzando el cursor.

Respuestas contempladas:

- `200` con `result.nextcode`: hay un código nuevo.
- `202`/`204` o `nextcode` vacío/`n/a`: no hay más códigos por ahora.
- `403`: el *game authentication code* es inválido o fue revocado.
- `429`: límite de la API.
- `5xx`/red: error transitorio, se reintenta en la próxima corrida.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

from app.services.matchmaking.sharecode import (
    ShareCodeError,
    canonical_share_code,
    decode_share_code,
)

STEAM_API_BASE_URL = "https://api.steampowered.com"
NEXT_SHARE_CODE_URL = (
    f"{STEAM_API_BASE_URL}/ICSGOPlayers_730/GetNextMatchSharingCode/v1/"
)
NO_MORE_CODES = {"", "N/A", "NA", "NONE", "NULL"}


class DiscoveryError(Exception):
    """Error controlado al consultar el historial de matchmaking."""

    def __init__(self, message, code="upstream_error", *, retryable=True):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


def is_configured():
    return bool(str(current_app.config.get("STEAM_API_KEY", "")).strip())


def _api_key():
    key = str(current_app.config.get("STEAM_API_KEY", "")).strip()
    if not key:
        raise DiscoveryError(
            "Steam Web API key is not configured",
            code="not_configured",
            retryable=False,
        )
    return key


_HTTP_ERRORS = {
    403: ("Steam rechazó el código de autenticación", "invalid_auth_code", False),
    429: ("Se alcanzó el límite de consultas de Steam", "rate_limited", True),
    400: ("Steam rechazó el share code conocido", "invalid_share_code", False),
}


def _http_failure(error):
    """Preserve the provider status taxonomy without exposing credentials."""
    if error.code in (202, 204):
        return None
    message, code, retryable = _HTTP_ERRORS.get(
        error.code, (f"Steam respondió HTTP {error.code}", "http_error", True)
    )
    raise DiscoveryError(message, code=code, retryable=retryable) from error


def _read_response(request, timeout):
    """Transport only: status and decoded body, or the no-more-codes sentinel."""
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return getattr(response, "status", 200), response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        _http_failure(error)
        return 204, ""
    except (URLError, TimeoutError, OSError) as error:
        raise DiscoveryError("No se pudo contactar a Steam", code="unavailable") from error


def _decode_next_code(raw):
    """Accept both supported result keys, with the historical precedence."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DiscoveryError("Steam devolvió una respuesta inválida", code="invalid_response") from error
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise DiscoveryError("Steam devolvió una respuesta inválida", code="invalid_response")
    return result.get("nextcode") or result.get("next_code")


def _request(steam_id, auth_code, known_code):
    query = urlencode(
        {
            "key": _api_key(),
            "steamid": str(steam_id),
            "steamidkey": str(auth_code),
            "knowncode": str(known_code),
        }
    )
    request = Request(
        f"{NEXT_SHARE_CODE_URL}?{query}",
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "cs2-manager-matchmaking/1.0",
        },
    )
    timeout = float(
        current_app.config.get("MATCHMAKING_API_TIMEOUT_SECONDS", 15)
    )
    status, raw = _read_response(request, timeout)
    if status in (202, 204):
        return None
    if not raw.strip():
        return None

    return _decode_next_code(raw)


def _validated_code(value, *, message, code, retryable=True):
    try:
        canonical = canonical_share_code(value)
        decode_share_code(canonical)
    except ShareCodeError as error:
        raise DiscoveryError(message, code=code, retryable=retryable) from error
    return canonical


def get_next_share_code(steam_id, auth_code, known_code):
    """Devuelve el siguiente share code canónico o `None` si no hay más."""
    if not steam_id or not auth_code:
        raise DiscoveryError(
            "Falta el SteamID o el código de autenticación",
            code="invalid_authorization",
            retryable=False,
        )
    known = _validated_code(
        known_code, message="El share code conocido no es válido",
        code="invalid_share_code", retryable=False,
    )

    value = _request(steam_id, auth_code, known)
    if value is None:
        return None
    text = str(value).strip()
    if text.upper() in NO_MORE_CODES:
        return None
    return _validated_code(text, message="Steam devolvió un share code inválido", code="invalid_response")
