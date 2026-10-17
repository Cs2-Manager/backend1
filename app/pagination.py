"""Paginación opcional y retrocompatible para los listados de la API.

Si el cliente no envía `page` ni `per_page` se devuelven todos los elementos
(comportamiento histórico). Cuando se envía alguno de los dos parámetros se
aplica la paginación y se agrega metadatos en la respuesta.
"""

from flask import request

from app.errors import ApiError

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100


def _to_int(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("page and per_page must be integers", status_code=400)


def paginate(query):
    """Devuelve (items, meta) aplicando paginación opcional."""
    page_raw = request.args.get("page")
    per_page_raw = request.args.get("per_page")

    if page_raw is None and per_page_raw is None:
        items = query.all()
        return items, {"total": len(items)}

    page = max(_to_int(page_raw, 1), 1)
    per_page = _to_int(per_page_raw, DEFAULT_PER_PAGE)
    per_page = min(max(per_page, 1), MAX_PER_PAGE)

    total = query.order_by(None).count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return items, {"total": total, "page": page, "per_page": per_page}
