"""Serializadores de mapas y callouts."""


def serialize_callout_public(callout):
    return {
        "id": callout.id,
        "map_id": callout.map_id,
        "zone_name": callout.zone_name,
        "x_ratio": callout.x_ratio,
        "y_ratio": callout.y_ratio,
    }


def serialize_map_public(map_obj):
    return {
        "id": map_obj.id,
        "name": map_obj.name,
        "image_url": map_obj.image_url,
        "active_pool": map_obj.active_pool,
        "callouts": [serialize_callout_public(item) for item in map_obj.callouts],
    }


def serialize_map_admin(map_obj):
    """El mapa no tiene campos internos; el contexto admin usa la misma forma."""
    return serialize_map_public(map_obj)
