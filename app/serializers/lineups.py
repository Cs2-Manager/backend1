"""Serializadores de lineups de granadas.

Se exponen formas explícitas por contexto para que una lineup PERSONAL nunca
se filtre con los mismos campos que una OFFICIAL o una de equipo. La capa de
servicios decide qué serializador usar después de resolver el permiso.
"""


def _iso(value):
    return value.isoformat() if value else None


def _canonical_type(value):
    key = str(value or "").strip().lower()
    return {
        "smoke": "SMOKE",
        "flash": "FLASH",
        "flashbang": "FLASH",
        "molotov": "MOLOTOV",
        "incendiary": "INCENDIARY",
        "he": "HE",
        "he grenade": "HE",
        "decoy": "DECOY",
    }.get(key, str(value or "").upper())


def _canonical_side(value):
    key = str(value or "").strip().upper()
    return "T" if key in ("TR", "T") else key


def serialize_grenade_media(media):
    return {
        "id": media.id,
        "kind": media.kind,
        "url": media.url,
        "thumbnail_url": media.thumbnail_url,
        "position": media.position,
    }


def _related_value(resource, field):
    return getattr(resource, field) if resource else None


def _base(lineup):
    author = getattr(lineup, "author", None)
    team = getattr(lineup, "team", None)
    map_obj = getattr(lineup, "map", None)
    text_fields = {
        field: getattr(lineup, field) or ""
        for field in ("description", "launch_zone", "impact_zone", "throw_type",
                      "instructions", "notes", "game_version")
    }
    return {
        "id": lineup.id,
        "map_id": lineup.map_id,
        "map_name": _related_value(map_obj, "name"),
        "team_id": lineup.team_id,
        "team_name": _related_value(team, "name"),
        "scope": lineup.scope,
        "type": lineup.type,
        "grenade_type": _canonical_type(lineup.type),
        "side": _canonical_side(lineup.side),
        "title": lineup.title,
        **text_fields,
        "video_url": lineup.video_url,
        "image_url": lineup.image_url,
        "difficulty": lineup.difficulty,
        "status": lineup.status,
        "visibility": lineup.visibility,
        "launch_position": lineup.launch_position,
        "impact_position": lineup.impact_position,
        "position": lineup.position,
        "launch_callout_id": lineup.launch_callout_id,
        "impact_callout_id": lineup.impact_callout_id,
        "tags": lineup.tags or [],
        "version": lineup.version,
        "author_id": lineup.author_id,
        "author_username": _related_value(author, "username"),
        "responsible_id": lineup.responsible_id,
        "source_lineup_id": lineup.source_lineup_id,
        "source_proposal_id": lineup.source_proposal_id,
        "created_at": _iso(lineup.created_at),
        "updated_at": _iso(lineup.updated_at),
    }


def serialize_lineup_public(lineup):
    """Forma histórica consumida por el dashboard y el catálogo."""
    return {
        **{
            key: getattr(lineup, key)
            for key in (
                "team_id",
                "author_id",
                "responsible_id",
                "visibility",
                "difficulty",
                "status",
                "launch_zone",
                "impact_zone",
                "position",
                "image_url",
            )
            if hasattr(lineup, key)
        },
        "id": lineup.id,
        "map_id": lineup.map_id,
        "type": lineup.type,
        "side": lineup.side,
        "title": lineup.title,
        "description": lineup.description,
        "video_url": lineup.video_url,
    }


def serialize_lineup_admin(lineup):
    return serialize_lineup_public(lineup)


def serialize_grenade_lineup_official(lineup, *, can_edit=False):
    payload = _base(lineup)
    payload.update(
        {
            "media": [serialize_grenade_media(item) for item in lineup.media],
            "can_edit": bool(can_edit),
            "is_official": True,
        }
    )
    return payload


def serialize_grenade_lineup_personal(lineup, *, can_edit=True):
    payload = _base(lineup)
    payload.update(
        {
            "media": [serialize_grenade_media(item) for item in lineup.media],
            "can_edit": bool(can_edit),
            "can_delete": bool(can_edit),
            "can_propose": bool(can_edit),
            "is_official": False,
        }
    )
    return payload


def serialize_grenade_lineup_team(lineup, *, can_edit=True, can_propose=False):
    payload = _base(lineup)
    payload.update(
        {
            "media": [serialize_grenade_media(item) for item in lineup.media],
            "can_edit": bool(can_edit),
            "can_delete": bool(can_edit),
            "can_propose": bool(can_propose),
            "is_official": False,
        }
    )
    return payload


def serialize_grenade_lineup(lineup, *, viewer=None, is_team_member=False):
    """Despacha al contexto correcto sin exponer campos de otro scope."""
    if lineup.scope == "OFFICIAL":
        from app.permissions.policies import can_manage_official_grenade

        return serialize_grenade_lineup_official(
            lineup, can_edit=can_manage_official_grenade(viewer)
        )
    if lineup.scope == "TEAM":
        return serialize_grenade_lineup_team(
            lineup, can_edit=bool(viewer and is_team_member)
        )
    from app.permissions.policies import can_edit_personal_grenade

    return serialize_grenade_lineup_personal(
        lineup,
        can_edit=can_edit_personal_grenade(viewer, lineup.author_id),
    )


def serialize_grenade_revision(revision):
    actor = getattr(revision, "actor", None)
    return {
        "id": revision.id,
        "lineup_id": revision.lineup_id,
        "version": revision.version,
        "actor_id": revision.actor_id,
        "actor_username": actor.username if actor else None,
        "action": revision.action,
        "change_summary": revision.change_summary or "",
        "snapshot": revision.snapshot,
        "created_at": _iso(revision.created_at),
    }


def serialize_grenade_proposal(proposal):
    author = getattr(proposal, "author", None)
    decided_by = getattr(proposal, "decided_by", None)
    return {
        "id": proposal.id,
        "team_id": proposal.team_id,
        "map_id": proposal.map_id,
        "source_lineup_id": proposal.source_lineup_id,
        "approved_lineup_id": proposal.approved_lineup_id,
        "author_id": proposal.author_id,
        "author_username": author.username if author else None,
        "decided_by_id": proposal.decided_by_id,
        "decided_by_username": decided_by.username if decided_by else None,
        "status": proposal.status,
        "note": proposal.note or "",
        "rejection_reason": proposal.rejection_reason or "",
        "snapshot": proposal.snapshot,
        "created_at": _iso(proposal.created_at),
        "decided_at": _iso(proposal.decided_at),
    }
