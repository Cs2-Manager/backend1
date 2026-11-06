"""Serializadores de mapas y callouts."""

from datetime import date, datetime


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def serialize_callout_public(callout):
    return {
        **{
            key: getattr(callout, key)
            for key in ("zone", "description", "image_url", "status", "author_id")
            if hasattr(callout, key)
        },
        "id": callout.id,
        "map_id": callout.map_id,
        "zone_name": callout.zone_name,
        "x_ratio": callout.x_ratio,
        "y_ratio": callout.y_ratio,
    }


def _map_base(map_obj):
    return {
        "id": map_obj.id,
        "name": map_obj.name,
        "slug": getattr(map_obj, "slug", None),
        "image_url": map_obj.image_url,
        "cover_url": getattr(map_obj, "cover_url", None),
        "description": getattr(map_obj, "description", ""),
        "active_pool": map_obj.active_pool,
        "category": getattr(map_obj, "category", "COMPETITIVE"),
        "status": getattr(map_obj, "status", "ACTIVE"),
        "display_order": getattr(map_obj, "display_order", 0),
        "release_date": _iso(getattr(map_obj, "release_date", None)),
    }


def serialize_map_public(map_obj):
    payload = _map_base(map_obj)
    payload.update(
        {
            "callouts": [serialize_callout_public(item) for item in map_obj.callouts],
        }
    )
    official_count = getattr(map_obj, "official_lineups_count", None)
    if official_count is not None:
        payload["official_lineups_count"] = int(official_count)
    return payload


def serialize_map_admin(map_obj):
    """Incluye metadatos de procedencia y mantenimiento del catálogo.

    Solo agrega las claves que el objeto realmente expone para conservar el
    contrato histórico de los serializadores sobre objetos mínimos.
    """
    payload = serialize_map_public(map_obj)
    for field, default in (
        ("image_source", None),
        ("top_down_source", None),
        ("visual_version", 1),
        ("created_at", None),
        ("updated_at", None),
    ):
        if hasattr(map_obj, field):
            payload[field] = _iso(getattr(map_obj, field, default))
    return payload
