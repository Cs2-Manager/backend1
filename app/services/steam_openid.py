"""Cliente mínimo de Steam OpenID 2.0.

Steam expone su inicio de sesión mediante OpenID 2.0. El flujo es:

1. Redirigir al usuario a `https://steamcommunity.com/openid/login`.
2. Recibir la respuesta en nuestro callback.
3. Reenviar los parámetros `openid.*` con `mode=check_authentication` para que
   Steam confirme la firma y el `claimed_id`.
4. Extraer el SteamID64 del `claimed_id` verificado.

Nunca se confía en un SteamID64 enviado por el frontend.
"""

import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
STEAM_OPENID_NAMESPACE = "http://specs.openid.net/auth/2.0"
STEAM_CLAIMED_ID_PREFIX = "https://steamcommunity.com/openid/id/"
STEAM_ID_PATTERN = re.compile(r"^7656\d{13}$")
STEAM_ID_MIN = 76561197960265728

REQUIRED_PARAMS = (
    "openid.mode",
    "openid.op_endpoint",
    "openid.claimed_id",
    "openid.identity",
    "openid.return_to",
)


class SteamOpenIDError(Exception):
    """Respuesta OpenID inválida o no verificable."""

    def __init__(self, message, code="verification_failed"):
        super().__init__(message)
        self.message = message
        self.code = code


def is_valid_steam_id(steam_id):
    """Valida el formato y el rango de un SteamID64 individual."""
    value = str(steam_id or "").strip()
    if not STEAM_ID_PATTERN.fullmatch(value):
        return False
    try:
        return int(value) >= STEAM_ID_MIN
    except ValueError:
        return False


def extract_steam_id(claimed_id):
    """Extrae y valida el SteamID64 de un `claimed_id` de Steam."""
    value = str(claimed_id or "").strip()
    if not value.startswith(STEAM_CLAIMED_ID_PREFIX):
        raise SteamOpenIDError("Invalid Steam claimed identifier")
    steam_id = value[len(STEAM_CLAIMED_ID_PREFIX) :]
    if not is_valid_steam_id(steam_id):
        raise SteamOpenIDError("Invalid SteamID64")
    return steam_id


def build_login_url(return_to, realm):
    """Construye la URL oficial de `checkid_setup` para Steam."""
    params = {
        "openid.ns": STEAM_OPENID_NAMESPACE,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": f"{STEAM_OPENID_NAMESPACE}/identifier_select",
        "openid.claimed_id": f"{STEAM_OPENID_NAMESPACE}/identifier_select",
    }
    return f"{STEAM_OPENID_ENDPOINT}?{urlencode(params)}"


def _openid_params(values):
    """Devuelve solo los parámetros `openid.*` de la respuesta."""
    return {
        key: value
        for key, value in values.items()
        if str(key).startswith("openid.")
    }


def _post_form(url, data):
    """POST `application/x-www-form-urlencoded` (monkeypatcheable en tests)."""
    body = urlencode(data).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "cs2-manager-steam/1.0",
        },
    )
    timeout = float(
        current_app.config.get("STEAM_OPENID_TIMEOUT_SECONDS", 10)
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _parse_key_value(body):
    parsed = {}
    for line in str(body or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def verify_response(values, expected_return_to):
    """Verifica una respuesta OpenID y devuelve el SteamID64 confirmado."""
    params = _openid_params(values)
    missing = [key for key in REQUIRED_PARAMS if not params.get(key)]
    if missing:
        raise SteamOpenIDError("Incomplete Steam OpenID response")

    if params["openid.mode"] != "id_res":
        raise SteamOpenIDError("Unexpected Steam OpenID mode")

    if params["openid.op_endpoint"] != STEAM_OPENID_ENDPOINT:
        raise SteamOpenIDError("Unexpected Steam OpenID endpoint")

    return_to = params["openid.return_to"].strip()
    expected = str(expected_return_to or "").strip()
    if not expected or return_to != expected:
        raise SteamOpenIDError("Steam OpenID return_to does not match")

    claimed_id = params["openid.claimed_id"].strip()
    identity = params["openid.identity"].strip()
    if identity != claimed_id:
        raise SteamOpenIDError("Steam OpenID identities do not match")

    steam_id = extract_steam_id(claimed_id)

    verification = dict(params)
    verification["openid.mode"] = "check_authentication"
    try:
        body = _post_form(STEAM_OPENID_ENDPOINT, verification)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SteamOpenIDError(
            "Steam OpenID verification is unavailable", code="unavailable"
        ) from error

    result = _parse_key_value(body)
    if result.get("is_valid", "").lower() != "true":
        raise SteamOpenIDError("Steam did not validate the OpenID response")

    return steam_id
