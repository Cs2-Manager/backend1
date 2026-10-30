"""Serializadores de mapas de la Steam Workshop."""


def _base(item):
    return {
        "id": item.id,
        "title": item.title,
        "category": item.category,
        "description": item.description,
        "image_url": item.image_url,
        "workshop_url": item.workshop_url,
    }


def serialize_workshop_map_public(item):
    return _base(item)


def serialize_workshop_map_admin(item):
    return _base(item)
