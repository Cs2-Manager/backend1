"""Utilidades de validación reutilizables por los servicios.

Mantener estas funciones en un único módulo evita duplicar la lógica de
limpieza y comprobación de campos entre los distintos recursos.
"""


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
