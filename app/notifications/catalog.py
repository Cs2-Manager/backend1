"""Catálogo de notificaciones persistentes.

Genera títulos, mensajes y recursos de solo datos. El frontend nunca recibe
HTML. Las plantillas deben coincidir con `NotificationFactory` de NestJS para
que el historial y la entrega en vivo muestren el mismo texto.
"""

GRENADE_TYPE_LABELS = {
    "SMOKE": "humo",
    "FLASH": "flash",
    "MOLOTOV": "molotov",
    "INCENDIARY": "incendiaria",
    "HE": "HE",
    "DECOY": "señuelo",
}

ROLE_LABELS = {
    "CAPTAIN": "capitán",
    "COACH": "entrenador",
    "PLAYER": "jugador",
}


def _grenade_type(value):
    return GRENADE_TYPE_LABELS.get(str(value or "").upper(), value or "")


def _role(value):
    return ROLE_LABELS.get(str(value or "").upper(), value or "")


def render_notification(event):
    """Devuelve los datos persistentes de una notificación o None.

    Solo los eventos de notificación se persisten. Los eventos `team.activity`
    se guardan en `team_activity` y no generan una notificación.
    """
    event_type = event.get("event_type")
    payload = event.get("payload") or {}
    base = {
        "event_id": event["event_id"],
        "event_type": event_type,
        "team_id": event.get("team_id"),
        "created_at": event.get("occurred_at"),
    }

    if event_type == "team.invitation.created":
        team = payload["team"]
        invited_by = payload["invited_by"]
        return {
            **base,
            "title": "Invitación recibida",
            "message": (
                f"{invited_by['username']} te invitó a {team['name']} "
                f"como {_role(payload.get('role'))}."
            ),
            "resource_type": "invitation",
            "resource_id": payload["invitation_id"],
            "path": "/invitations",
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": invited_by["username"],
                "role": payload.get("role"),
            },
        }

    if event_type == "team.invitation.accepted":
        team = payload["team"]
        member = payload["member"]
        return {
            **base,
            "title": "Invitación aceptada",
            "message": (
                f"{member['username']} aceptó la invitación a {team['name']}."
            ),
            "resource_type": "team",
            "resource_id": team["id"],
            "path": f"/teams/{team['id']}",
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": member["username"],
                "role": payload.get("role"),
            },
        }

    if event_type == "team.invitation.rejected":
        team = payload["team"]
        user = payload["user"]
        return {
            **base,
            "title": "Invitación rechazada",
            "message": (
                f"{user['username']} rechazó la invitación a {team['name']}."
            ),
            "resource_type": "team",
            "resource_id": team["id"],
            "path": f"/teams/{team['id']}",
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": user["username"],
            },
        }

    if event_type == "grenade.proposal.created":
        team = payload["team"]
        map_ref = payload["map"]
        lineup = payload["lineup"]
        author = payload["author"]
        return {
            **base,
            "title": "Nueva propuesta de granada",
            "message": (
                f"{author['username']} propuso \"{lineup['title']}\" "
                f"({map_ref['name']}, {_grenade_type(lineup.get('type'))}) "
                f"en {team['name']}."
            ),
            "resource_type": "grenade_proposal",
            "resource_id": payload["proposal_id"],
            "path": f"/teams/{team['id']}",
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": author["username"],
                "map_name": map_ref["name"],
                "lineup_type": lineup.get("type"),
                "lineup_title": lineup.get("title"),
            },
        }

    if event_type == "grenade.proposal.approved":
        team = payload["team"]
        map_ref = payload["map"]
        lineup = payload["lineup"]
        return {
            **base,
            "title": "Propuesta aprobada",
            "message": (
                f"Tu propuesta \"{lineup['title']}\" ({map_ref['name']}) "
                f"fue aprobada en {team['name']}."
            ),
            "resource_type": "team_lineup",
            "resource_id": payload["approved_lineup_id"],
            "path": (
                f"/teams/{team['id']}/lineups/"
                f"{payload['approved_lineup_id']}"
            ),
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": event.get("actor", {}).get("username", ""),
                "map_name": map_ref["name"],
                "lineup_type": lineup.get("type"),
                "lineup_title": lineup.get("title"),
            },
        }

    if event_type == "grenade.proposal.rejected":
        team = payload["team"]
        map_ref = payload["map"]
        lineup = payload["lineup"]
        return {
            **base,
            "title": "Propuesta rechazada",
            "message": (
                f"Tu propuesta \"{lineup['title']}\" ({map_ref['name']}) "
                f"fue rechazada en {team['name']}."
            ),
            "resource_type": "grenade_proposal",
            "resource_id": payload["proposal_id"],
            "path": f"/teams/{team['id']}",
            "metadata": {
                "team_name": team["name"],
                "team_tag": team.get("tag"),
                "actor_username": event.get("actor", {}).get("username", ""),
                "map_name": map_ref["name"],
                "lineup_type": lineup.get("type"),
                "lineup_title": lineup.get("title"),
            },
        }

    return None
