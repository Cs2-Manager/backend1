"""Cifrado simétrico del *game authentication code* de Steam.

El código permite consultar el historial de matchmaking del jugador, así que
nunca se guarda en claro. Se cifra con Fernet (AES-128-CBC + HMAC-SHA256) y una
clave derivada del secreto de la aplicación:

    clave = base64url(sha256(MATCHMAKING_SECRET_KEY))

`MATCHMAKING_SECRET_KEY` puede definirse aparte para no depender del
`SECRET_KEY` general, pero si falta se usa este último. Rotar el secreto
invalida los códigos guardados: la autorización pasa a `INVALID` y el jugador
debe volver a generarla (no se pierde nada más).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class CryptoError(Exception):
    """No se pudo cifrar o descifrar un secreto."""


def _secret():
    return str(
        current_app.config.get("MATCHMAKING_SECRET_KEY")
        or current_app.config.get("SECRET_KEY")
        or ""
    )


def _fernet():
    secret = _secret()
    if not secret:
        raise CryptoError("No hay secreto configurado para cifrar")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    """Cifra un texto y devuelve el token ASCII de Fernet."""
    if not value:
        raise CryptoError("No hay valor para cifrar")
    try:
        return _fernet().encrypt(str(value).encode("utf-8")).decode("ascii")
    except (CryptoError, ValueError) as error:
        raise CryptoError("No se pudo cifrar el código de autenticación") from error


def decrypt_secret(token):
    """Descifra un token de Fernet. Devuelve `None` si no es válido."""
    if not token:
        return None
    try:
        return _fernet().decrypt(str(token).encode("utf-8")).decode("utf-8")
    except (CryptoError, InvalidToken, ValueError, TypeError):
        return None
