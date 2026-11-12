"""Utilidades de validación reutilizables por los servicios.

Mantener estas funciones en un único módulo evita duplicar la lógica de
limpieza y comprobación de campos entre los distintos recursos.
"""

from urllib.parse import urlparse


def clean_str(value):
    """Devuelve la representación en texto, sin espacios, de un valor."""
    if value is None:
        return ""
    return str(value).strip()


def require_fields(data, fields):
    """Devuelve un diccionario {campo: mensaje} con los campos faltantes."""
    return {
        field: f"{field} is required"
        for field in fields
        if not clean_str(data.get(field))
    }


def validate_choice(value, allowed, field, errors):
    """Valida que `value` pertenezca a `allowed`, registrando el error."""
    if value not in allowed:
        errors[field] = f"{field} must be one of {', '.join(allowed)}"
    return errors


def parse_float(value, field, errors):
    """Convierte `value` a float, registrando el error si no es numérico."""
    try:
        return float(value)
    except (TypeError, ValueError):
        errors[field] = f"{field} must be numeric"
        return None


def parse_ratio(value, field, errors):
    """Convierte `value` a float y valida el rango [0, 1]."""
    number = parse_float(value, field, errors)
    if number is None:
        return None
    if not 0 <= number <= 1:
        errors[field] = f"{field} must be between 0 and 1"
        return None
    return number


def _validate_url_host(parsed, allowed_host, field, errors):
    """Valida el host de una URL ya parseada."""
    if allowed_host:
        hostname = (parsed.hostname or "").lower()
        if hostname != allowed_host and not hostname.endswith(f".{allowed_host}"):
            errors[field] = f"{field} must point to {allowed_host}"
            return False
    return True


def _url_text(value, field, errors, max_length):
    text = clean_str(value)
    if not text:
        return None
    if len(text) > max_length:
        errors[field] = f"{field} must be at most {max_length} characters"
        return None
    return text


def _url_parts(text, field, errors):
    try:
        parsed = urlparse(text)
    except ValueError:
        errors[field] = f"{field} must be a valid URL"
        return None
    return parsed


def _url_security_error(parsed, field):
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"{field} must be an http(s) URL"
    if parsed.username or parsed.password:
        return f"{field} must not include credentials"
    return None


def parse_url(value, field, errors, *, allowed_host=None, max_length=500):
    """Validate optional HTTP(S) text, credential safety and an optional host."""
    text = _url_text(value, field, errors, max_length)
    if text is None:
        return None
    parsed = _url_parts(text, field, errors)
    if parsed is None:
        return None
    error = _url_security_error(parsed, field)
    if error:
        errors[field] = error
        return None
    if not _validate_url_host(parsed, allowed_host, field, errors):
        return None
    return text


def _is_bool(value):
    return isinstance(value, bool)


def _non_negative_integer(value):
    if _is_bool(value):
        raise ValueError("Boolean is not an integer counter")
    number = int(value)
    if number < 0:
        raise ValueError("Negative counter")
    return number


def parse_non_negative_int(value, field, errors, *, default=0):
    """Convierte un valor a entero no negativo, registrando el error."""
    if value is None or value == "":
        return default
    try:
        return _non_negative_integer(value)
    except (TypeError, ValueError):
        errors[field] = f"{field} must be a non-negative integer"
        return default
