"""Servicio de mapas, catálogo y zonas (callouts)."""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.errors import ApiError
from app.extensions import db
from app.models.lineup import Lineup
from app.models.map import MAP_CATEGORIES, MAP_STATUSES, Callout, Map
from app.validators import clean_str, parse_ratio, parse_url

REQUIRED_MAP_FIELDS = ("name", "image_url")
REQUIRED_CALLOUT_FIELDS = ("zone_name", "x_ratio", "y_ratio")
SLUG_MAX = 80


def _official_count_subquery():
    return (
        db.session.query(func.count(Lineup.id))
        .filter(
            Lineup.map_id == Map.id,
            Lineup.scope == "OFFICIAL",
            Lineup.status == "PUBLISHED",
        )
        .correlate(Map)
        .scalar_subquery()
    )


def attach_official_counts(maps):
    """Anota cada mapa con la cantidad de lineups oficiales publicadas."""
    maps = list(maps)
    if not maps:
        return maps
    rows = (
        db.session.query(Lineup.map_id, func.count(Lineup.id))
        .filter(
            Lineup.map_id.in_([item.id for item in maps]),
            Lineup.scope == "OFFICIAL",
            Lineup.status == "PUBLISHED",
        )
        .group_by(Lineup.map_id)
        .all()
    )
    counts = dict(rows)
    for item in maps:
        item.official_lineups_count = counts.get(item.id, 0)
    return maps


def list_maps(filters=None):
    """Devuelve la consulta de mapas ordenada según el catálogo."""
    filters = filters or {}
    query = db.session.query(Map).options(selectinload(Map.callouts))
    if filters.get("q"):
        query = query.filter(Map.name.icontains(str(filters["q"])[:80], autoescape=True))

    pool = filters.get("pool", "all")
    if pool not in ("all", "active", "reserve"):
        raise ApiError("Invalid pool filter", status_code=400)
    if pool != "all":
        query = query.filter(Map.active_pool.is_(pool == "active"))

    category = filters.get("category")
    if category:
        category = str(category).strip().upper()
        if category not in MAP_CATEGORIES:
            raise ApiError("Invalid map category", status_code=400)
        query = query.filter(Map.category == category)

    status = filters.get("status")
    if status:
        status = str(status).strip().upper()
        if status not in MAP_STATUSES and status != "ALL":
            raise ApiError("Invalid map status", status_code=400)
        if status != "ALL":
            query = query.filter(Map.status == status)
    elif not filters.get("include_archived"):
        query = query.filter(Map.status == "ACTIVE")

    order = filters.get("sort", "name")
    if order not in ("name", "name_desc", "pool", "display_order", "updated"):
        raise ApiError("Invalid map sort", status_code=400)
    if order == "pool":
        query = query.order_by(Map.active_pool.desc(), Map.name)
    elif order == "display_order":
        query = query.order_by(Map.display_order, Map.name)
    elif order == "updated":
        query = query.order_by(Map.updated_at.desc(), Map.id)
    else:
        query = query.order_by(
            Map.name.desc() if order == "name_desc" else Map.name, Map.id
        )
    return query


def _slugify(value):
    import re

    normalized = re.sub(r"[^a-z0-9]+", "-", clean_str(value).lower())
    return normalized.strip("-")[:SLUG_MAX] or None


def _metadata(data, *, current=None):
    errors, values = {}, {}
    if "description" in data:
        value = data["description"]
        if not isinstance(value, str) or len(value) > 4000:
            errors["description"] = "description must be text up to 4000 characters"
        else:
            values["description"] = value.strip()
    if "cover_url" in data:
        values["cover_url"] = parse_url(data["cover_url"], "cover_url", errors)

    if "slug" in data:
        slug = _slugify(data["slug"])
        if not slug:
            errors["slug"] = "slug must contain letters or numbers"
        else:
            existing = (
                db.session.query(Map.id)
                .filter(Map.slug == slug, Map.id != (current.id if current else 0))
                .first()
            )
            if existing:
                errors["slug"] = "slug already exists"
            values["slug"] = slug

    if "category" in data:
        category = clean_str(data["category"]).upper()
        if category not in MAP_CATEGORIES:
            errors["category"] = f"category must be one of {', '.join(MAP_CATEGORIES)}"
        else:
            values["category"] = category

    if "status" in data:
        status = clean_str(data["status"]).upper()
        if status not in MAP_STATUSES:
            errors["status"] = f"status must be one of {', '.join(MAP_STATUSES)}"
        else:
            values["status"] = status

    for field in ("image_source", "top_down_source"):
        if field in data:
            value = data[field]
            if value is None or value == "":
                values[field] = None
            elif not isinstance(value, str) or len(value) > 300:
                errors[field] = f"{field} must be text up to 300 characters"
            else:
                values[field] = value.strip()

    if "visual_version" in data:
        values["visual_version"] = _parse_positive_int(
            data["visual_version"], "visual_version", errors, minimum=1
        )
    if "display_order" in data:
        values["display_order"] = _parse_positive_int(
            data["display_order"], "display_order", errors, minimum=0
        )
    if "release_date" in data:
        values["release_date"] = _parse_date(data["release_date"], "release_date", errors)

    if errors:
        raise ApiError("Invalid map", status_code=400, fields=errors)
    return values


def _parse_positive_int(value, field, errors, *, minimum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors[field] = f"{field} must be an integer"
        return None
    if parsed < minimum:
        errors[field] = f"{field} must be >= {minimum}"
    return parsed


def _parse_date(value, field, errors):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors[field] = f"{field} must be an ISO date (YYYY-MM-DD)"
        return None


def get_map(map_id):
    """Devuelve un mapa o lanza ApiError 404."""
    map_obj = db.session.get(Map, map_id)
    if map_obj is None:
        raise ApiError("Map not found", status_code=404)
    attach_official_counts([map_obj])
    return map_obj


def _unique_slug(slug, *, exclude_id=None):
    query = db.session.query(Map.id).filter(Map.slug == slug)
    if exclude_id:
        query = query.filter(Map.id != exclude_id)
    return query.first() is None


def create_map(data):
    metadata = _metadata(data)
    errors = {}
    name = clean_str(data.get("name"))
    image_url = clean_str(data.get("image_url"))
    if not name:
        errors["name"] = "name is required"
    if not image_url:
        errors["image_url"] = "image_url is required"
    if errors:
        raise ApiError("Invalid map", status_code=400, fields=errors)

    if db.session.query(Map.id).filter_by(name=name).first():
        raise ApiError("Map name already exists", status_code=409)

    if "slug" not in metadata:
        base = _slugify(name) or "map"
        slug = base
        suffix = 1
        while not _unique_slug(slug):
            suffix += 1
            slug = f"{base}-{suffix}"[:SLUG_MAX]
        metadata["slug"] = slug

    new_map = Map(
        name=name,
        image_url=image_url,
        active_pool=bool(data.get("active_pool", False)),
        **metadata,
    )
    db.session.add(new_map)
    db.session.commit()
    return new_map


def update_map(map_id, data):
    current = get_map(map_id)
    metadata = _metadata(data, current=current)

    if "name" in data:
        name = clean_str(data["name"])
        if not name:
            raise ApiError("name cannot be empty", status_code=400)
        existing = (
            db.session.query(Map.id)
            .filter(Map.name == name, Map.id != map_id)
            .first()
        )
        if existing:
            raise ApiError("Map name already exists", status_code=409)
        current.name = name
    if "image_url" in data:
        new_image = clean_str(data["image_url"])
        if new_image != current.image_url:
            # La nueva representación visual invalida la referencia anterior.
            current.visual_version = (current.visual_version or 1) + 1
        current.image_url = new_image
    if "active_pool" in data:
        current.active_pool = bool(data["active_pool"])
    for field, value in metadata.items():
        setattr(current, field, value)

    db.session.commit()
    return current


def archive_map(map_id):
    current = get_map(map_id)
    current.status = "ARCHIVED"
    current.active_pool = False
    db.session.commit()
    return current


def unarchive_map(map_id):
    """Revierte el archivado sin tocar el resto de los metadatos."""
    current = get_map(map_id)
    current.status = "ACTIVE"
    db.session.commit()
    return current


def _map_has_references(map_id):
    """Indica si el mapa está referenciado por contenido que debe preservarse.

    Se consultan explícitamente todas las tablas con FK a ``maps`` para no
    depender de cascadas destructivas ni de restricciones RESTRICT que
    terminarían en un error 500 al intentar borrar.
    """
    from app.models.grenade_lineup import TeamGrenadeLineupProposal
    from app.models.player_profile import PlayerMapStats, PlayerMatch
    from app.models.tactics import TeamMapSetup, TeamStrategy
    from app.models.team_lineup import TeamLineup

    checks = (
        (Lineup, Lineup.map_id),
        (Callout, Callout.map_id),
        (TeamStrategy, TeamStrategy.map_id),
        (TeamLineup, TeamLineup.map_id),
        (TeamMapSetup, TeamMapSetup.map_id),
        (TeamGrenadeLineupProposal, TeamGrenadeLineupProposal.map_id),
        (PlayerMapStats, PlayerMapStats.map_id),
        (PlayerMatch, PlayerMatch.map_id),
    )
    return any(
        db.session.query(model.id).filter(column == map_id).first() is not None
        for model, column in checks
    )


def delete_map(map_id):
    """Elimina un mapa sin referencias o lo archiva si está en uso.

    Preservar lineups, estrategias, callouts, map setups y estadísticas es
    obligatorio: nunca se borra en cascada contenido existente. Si una FK no
    prevista impide el DELETE, se revierte la transacción y se archiva.
    """
    from sqlalchemy.exc import IntegrityError

    current = get_map(map_id)
    if _map_has_references(map_id):
        current.status = "ARCHIVED"
        current.active_pool = False
        db.session.commit()
        return {"archived": True}

    db.session.delete(current)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current = db.session.get(Map, map_id)
        if current is None:
            raise
        current.status = "ARCHIVED"
        current.active_pool = False
        db.session.commit()
        return {"archived": True}
    return {"archived": False}


def list_callouts(map_id):
    return get_map(map_id).callouts


def get_callout(map_id, callout_id):
    get_map(map_id)
    callout = db.session.get(Callout, callout_id)
    if callout is None or callout.map_id != map_id:
        raise ApiError("Callout not found", status_code=404)
    return callout


def create_callout(map_id, data, author=None):
    get_map(map_id)

    errors = {}
    zone_name = clean_str(data.get("zone_name"))
    if not zone_name:
        errors["zone_name"] = "zone_name is required"
    if data.get("x_ratio") is None:
        errors["x_ratio"] = "x_ratio is required"
    if data.get("y_ratio") is None:
        errors["y_ratio"] = "y_ratio is required"

    x_ratio = y_ratio = None
    if not errors:
        x_ratio = parse_ratio(data["x_ratio"], "x_ratio", errors)
        y_ratio = parse_ratio(data["y_ratio"], "y_ratio", errors)
    if errors:
        raise ApiError("Invalid callout", status_code=400, fields=errors)

    callout = Callout(
        map_id=map_id,
        zone_name=zone_name,
        x_ratio=x_ratio,
        y_ratio=y_ratio,
        author_id=author.id if author else None,
        **_callout_metadata(data),
    )
    _unique_callout(map_id, zone_name)
    db.session.add(callout)
    db.session.commit()
    return callout


def update_callout(map_id, callout_id, data):
    callout = get_callout(map_id, callout_id)
    errors = {}
    metadata = _callout_metadata(data)

    if "zone_name" in data:
        zone_name = clean_str(data["zone_name"])
        if not zone_name:
            errors["zone_name"] = "zone_name cannot be empty"
        else:
            _unique_callout(map_id, zone_name, callout_id)
            callout.zone_name = zone_name

    for key in ("x_ratio", "y_ratio"):
        if key in data:
            value = parse_ratio(data[key], key, errors)
            if value is not None:
                setattr(callout, key, value)

    if errors:
        raise ApiError("Invalid callout", status_code=400, fields=errors)
    for field, value in metadata.items():
        setattr(callout, field, value)

    db.session.commit()
    return callout


def delete_callout(map_id, callout_id):
    callout = get_callout(map_id, callout_id)
    db.session.delete(callout)
    db.session.commit()


def _unique_callout(map_id, name, exclude=None):
    from sqlalchemy import func

    query = db.session.query(Callout.id).filter(
        Callout.map_id == map_id, func.lower(Callout.zone_name) == name.lower()
    )
    if exclude:
        query = query.filter(Callout.id != exclude)
    if query.first():
        raise ApiError("Callout already exists on this map", status_code=409)


def _callout_metadata(data):
    from app.services.tactical_validation import text, invalid

    values = {}
    for field, maximum in [("zone", 120), ("description", 4000)]:
        if field in data:
            values[field] = text(data[field], maximum)
    if "status" in data:
        if data["status"] not in ("DRAFT", "PUBLISHED", "ARCHIVED"):
            invalid("Invalid callout status")
        values["status"] = data["status"]
    if "image_url" in data:
        from app.services.media_validation import demonstration_url

        values["image_url"] = demonstration_url(data["image_url"])
    return values
