"""Cliente HTTP servidor-a-servidor hacia el servicio realtime.

Los eventos se envían después del commit de la operación de negocio. Cualquier
fallo (servicio caído, timeout, rechazo HMAC) se registra de forma sanitizada y
se descarta: una notificación perdida nunca revierte la operación de Flask.
"""

import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from .signature import sign


def _base_url():
    return str(current_app.config.get("REALTIME_URL", "")).rstrip("/")


def _secret():
    return str(current_app.config.get("REALTIME_HMAC_SECRET", "")).strip()


def is_enabled():
    return bool(current_app.config.get("REALTIME_ENABLED", False))


def publish_event(event):
    """Publica un evento ya construido. Devuelve True si fue aceptado.

    No propaga excepciones: el llamador continúa con la respuesta al cliente
    aunque el servicio realtime no esté disponible.
    """
    if not is_enabled():
        return False

    secret = _secret()
    if not secret:
        current_app.logger.warning(
            "Realtime disabled: REALTIME_HMAC_SECRET is not configured"
        )
        return False

    event_type = event.get("event_type", "unknown")
    body = json.dumps(
        event, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = sign(secret, timestamp, nonce, body)

    request = Request(
        f"{_base_url()}/internal/events",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Realtime-Timestamp": timestamp,
            "X-Realtime-Nonce": nonce,
            "X-Realtime-Signature": signature,
        },
    )

    timeout = float(current_app.config.get("REALTIME_TIMEOUT_SECONDS", 2))
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            response.read()
        return True
    except HTTPError as error:
        current_app.logger.warning(
            "Realtime event %s rejected with HTTP %s", event_type, error.code
        )
    except (URLError, TimeoutError, OSError):
        current_app.logger.warning(
            "Realtime service unavailable; event %s was not delivered",
            event_type,
        )
    except Exception:  # noqa: BLE001 - nunca romper la operación de negocio
        current_app.logger.warning(
            "Realtime event %s could not be published", event_type
        )
    return False
