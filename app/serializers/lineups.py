"""Serializadores de lineups."""


def _base(lineup):
    return {
        "id": lineup.id,
        "map_id": lineup.map_id,
        "type": lineup.type,
        "side": lineup.side,
        "title": lineup.title,
        "description": lineup.description,
        "video_url": lineup.video_url,
    }


def serialize_lineup_public(lineup):
    return _base(lineup)


def serialize_lineup_admin(lineup):
    """Los campos internos de autoría/equipo se agregarán en la Fase 1."""
    return _base(lineup)
