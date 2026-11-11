"""Firma HMAC-SHA256 compartida con el servicio realtime.

El formato canónico es exactamente el mismo que valida NestJS:

    HMAC-SHA256(secret, f"{timestamp}.{nonce}." + raw_body)

Se firma el cuerpo en bytes, no una reserialización JSON, para que cualquier
cambio (espacios, orden de claves, etc.) invalide la firma.
"""

import hashlib
import hmac


def sign(secret, timestamp, nonce, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    message = f"{timestamp}.{nonce}.".encode("utf-8") + body
    return hmac.new(
        secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def verify(secret, timestamp, nonce, body, signature):
    """Compara en tiempo constante y tolera firmas malformadas."""
    if not isinstance(signature, str):
        return False
    candidate = signature.strip().lower()
    if len(candidate) != 64:
        return False
    try:
        int(candidate, 16)
    except ValueError:
        return False
    expected = sign(secret, timestamp, nonce, body)
    return hmac.compare_digest(expected, candidate)
