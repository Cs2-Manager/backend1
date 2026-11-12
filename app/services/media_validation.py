"""Browser-loaded demonstrations only; never downloads external content."""
import ipaddress
from urllib.parse import urlparse
from app.validators import parse_url
from app.errors import ApiError


def demonstration_url(value):
    return public_https_url(value, field="image_url")


def _https_port_allowed(parsed):
    try:
        return parsed.port in (None, 443)
    except ValueError:
        return False


def _https_origin_allowed(parsed, host):
    return (
        parsed.scheme == "https" and _https_port_allowed(parsed)
        and "." in host and not host.endswith((".local", ".localhost", ".internal"))
    )


def _ip_address_error(host):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    return None if address.is_global else "Private addresses are not allowed"


def _validate_media_origin(parsed, field, errors):
    host = parsed.hostname or ""
    if not _https_origin_allowed(parsed, host):
        errors[field] = "Use a public HTTPS URL"
    address_error = _ip_address_error(host)
    if address_error:
        errors[field] = address_error


def public_https_url(value, *, field="url"):
    """Valida una URL HTTPS pública sin descargar contenido externo."""
    errors = {}
    result = parse_url(value, field, errors)
    if result:
        _validate_media_origin(urlparse(result), field, errors)
    if errors:
        raise ApiError("Invalid media URL", status_code=400, fields=errors)
    return result
