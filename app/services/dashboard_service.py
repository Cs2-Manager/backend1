"""Servicio del dashboard principal.

Agrupa las métricas de la biblioteca en una sola consulta para que la página
de inicio no tenga que descargar colecciones completas.
"""

from sqlalchemy import func

from app.extensions import db
from app.models.lineup import GRENADE_TYPES, Lineup
from app.models.map import Callout, Map
from app.models.workshop_map import WorkshopMap

RECENT_LIMIT = 5
ACTIVE_MAPS_LIMIT = 6


def _count(query):
    return query.scalar() or 0


def _map_summary():
    return {
        "total": _count(db.session.query(func.count(Map.id))),
        "active_pool": _count(
            db.session.query(func.count(Map.id)).filter(Map.active_pool.is_(True))
        ),
        "callouts": _count(db.session.query(func.count(Callout.id))),
    }


def _lineup_summary():
    rows = (
        db.session.query(Lineup.type, func.count(Lineup.id))
        .group_by(Lineup.type)
        .all()
    )
    counts = dict(rows)
    return {
        "total": _count(db.session.query(func.count(Lineup.id))),
        "by_type": [
            {"type": grenade_type, "count": counts.get(grenade_type, 0)}
            for grenade_type in GRENADE_TYPES
        ],
    }


def _workshop_summary():
    return {
        "total": _count(db.session.query(func.count(WorkshopMap.id))),
        "categories": _count(
            db.session.query(func.count(func.distinct(WorkshopMap.category)))
        ),
    }


def _active_maps():
    rows = (
        db.session.query(
            Map.id,
            Map.name,
            Map.image_url,
            func.count(Callout.id),
        )
        .outerjoin(Callout, Callout.map_id == Map.id)
        .filter(Map.active_pool.is_(True))
        .group_by(Map.id, Map.name, Map.image_url)
        .order_by(Map.name)
        .limit(ACTIVE_MAPS_LIMIT)
        .all()
    )
    return [
        {
            "id": map_id,
            "name": name,
            "image_url": image_url,
            "callouts_count": callouts_count,
        }
        for map_id, name, image_url, callouts_count in rows
    ]


def _recent_lineups():
    rows = (
        db.session.query(Lineup, Map.name)
        .join(Map, Lineup.map_id == Map.id)
        .order_by(Lineup.id.desc())
        .limit(RECENT_LIMIT)
        .all()
    )
    return [
        {
            "id": lineup.id,
            "title": lineup.title,
            "type": lineup.type,
            "side": lineup.side,
            "map_id": lineup.map_id,
            "map_name": map_name,
        }
        for lineup, map_name in rows
    ]


def get_dashboard():
    """Devuelve el resumen agregado que consume la página de inicio."""
    return {
        "summary": {
            "maps": _map_summary(),
            "lineups": _lineup_summary(),
            "workshop_maps": _workshop_summary(),
        },
        "active_maps": _active_maps(),
        "recent_lineups": _recent_lineups(),
    }
