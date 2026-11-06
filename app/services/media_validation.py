"""Browser-loaded demonstrations only; never downloads external content."""
import ipaddress
from urllib.parse import urlparse
from app.validators import parse_url
from app.errors import ApiError


def demonstration_url(value):
    return public_https_url(value, field="image_url")


def public_https_url(value, *, field="url"):
    """Valida una URL HTTPS pública sin descargar contenido externo."""
    errors = {}
    result = parse_url(value, field, errors)
    if result:
        parsed = urlparse(result)
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if (
            parsed.scheme != "https"
            or port not in (None, 443)
            or "." not in host
            or host.endswith((".local", ".localhost", ".internal"))
        ):
            errors[field] = "Use a public HTTPS URL"
        try:
            if not ipaddress.ip_address(host).is_global:
                errors[field] = "Private addresses are not allowed"
        except ValueError:
            pass
    if errors:
        raise ApiError("Invalid media URL", status_code=400, fields=errors)
    return result

