"""Pruebas de notificaciones persistentes, outbox y actividad de equipo.

Cubren la parte Flask de las etapas 5–7: persistencia transaccional, historial
paginado, contador, lectura individual/masiva, privacidad al cambiar de equipo
y consulta de actividad solo para integrantes actuales.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import (
    Notification,
    NotificationRecipient,
    RealtimeOutbox,
    Team,
    TeamActivity,
    TeamMember,
    User,
)
from app.notifications.outbox import queue_event, run_once
from app.security import generate_token, hash_password


def _user(username, *, admin=False):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
        is_admin=admin,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _team(name="Notify Team", tag="NTM", visibility="PRIVATE"):
    team = Team(name=name, tag=tag, visibility=visibility)
    db.session.add(team)
    db.session.flush()
    return team


def _member(team, user, role="PLAYER"):
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
    db.session.flush()


def _add_notification(user, *, title, minutes_ago=0, event_type="team.invitation.created"):
    notification = Notification(
        event_id=f"evt-{user.id}-{title}-{minutes_ago}",
        event_type=event_type,
        team_id=None,
        resource_type="invitation",
        resource_id=1,
        path="/invitations",
        title=title,
        message="Mensaje",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.session.add(notification)
    db.session.flush()
    db.session.add(
        NotificationRecipient(
            notification_id=notification.id,
            user_id=user.id,
            created_at=notification.created_at,
        )
    )
    db.session.commit()
    return notification


def test_invitation_notification_is_persisted_without_outbox(app, client):
    captain = _user("notify-captain")
    invitee = _user("notify-invitee")
    team = _team()
    _member(team, captain, "CAPTAIN")
    db.session.commit()

    response = client.post(
        f"/api/teams/{team.id}/invitations",
        json={"user_id": invitee.id, "role": "PLAYER"},
        headers=_headers(captain),
    )
    assert response.status_code == 201, response.get_json()

    notification = db.session.query(Notification).one()
    assert notification.event_type == "team.invitation.created"
    assert notification.title == "Invitación recibida"
    assert notification.team_id == team.id

    recipient = db.session.query(NotificationRecipient).one()
    assert recipient.user_id == invitee.id
    assert recipient.read_at is None

    # Realtime deshabilitado en pruebas: no se crea una outbox imposible.
    assert db.session.query(RealtimeOutbox).count() == 0

    history = client.get("/api/notifications", headers=_headers(invitee))
    assert history.status_code == 200, history.get_json()
    body = history.get_json()
    assert body["unread_count"] == 1
    assert len(body["notifications"]) == 1
    assert body["notifications"][0]["notification_id"] == notification.id
    assert body["notifications"][0]["read"] is False
    assert body["notifications"][0]["resource"]["path"] == "/invitations"


def test_history_pagination_order_and_read_actions(app, client):
    user = _user("notify-reader")
    db.session.commit()
    first = _add_notification(user, title="Primera", minutes_ago=30)
    second = _add_notification(user, title="Segunda", minutes_ago=10)
    third = _add_notification(user, title="Tercera", minutes_ago=0)

    page_one = client.get(
        "/api/notifications?page=1&per_page=2", headers=_headers(user)
    )
    assert page_one.status_code == 200, page_one.get_json()
    body = page_one.get_json()
    assert body["meta"] == {"total": 3, "page": 1, "per_page": 2}
    assert [item["title"] for item in body["notifications"]] == [
        "Tercera",
        "Segunda",
    ]
    assert body["unread_count"] == 3

    page_two = client.get(
        "/api/notifications?page=2&per_page=2", headers=_headers(user)
    )
    assert [item["title"] for item in page_two.get_json()["notifications"]] == [
        "Primera"
    ]

    marked = client.post(
        f"/api/notifications/{second.id}/read", headers=_headers(user)
    )
    assert marked.status_code == 200, marked.get_json()
    assert marked.get_json()["unread_count"] == 2
    assert marked.get_json()["notification"]["read"] is True

    # Marcar la misma notificación dos veces es idempotente.
    again = client.post(
        f"/api/notifications/{second.id}/read", headers=_headers(user)
    )
    assert again.status_code == 200
    assert again.get_json()["unread_count"] == 2

    all_read = client.post("/api/notifications/read-all", headers=_headers(user))
    assert all_read.status_code == 200
    assert all_read.get_json() == {"updated": 2, "unread_count": 0}

    count = client.get(
        "/api/notifications/unread-count", headers=_headers(user)
    )
    assert count.get_json() == {"unread_count": 0}

    # Un usuario distinto no puede marcar una notificación ajena.
    other = _user("notify-other")
    db.session.commit()
    forbidden = client.post(
        f"/api/notifications/{first.id}/read", headers=_headers(other)
    )
    assert forbidden.status_code == 404


def test_notification_privacy_follows_current_team_membership(app, client):
    captain = _user("privacy-captain")
    coach = _user("privacy-coach")
    invitee = _user("privacy-invitee")
    team = _team()
    _member(team, captain, "CAPTAIN")
    _member(team, coach, "COACH")
    db.session.commit()

    invitation = client.post(
        f"/api/teams/{team.id}/invitations",
        json={"user_id": invitee.id, "role": "PLAYER"},
        headers=_headers(captain),
    ).get_json()["invitation"]
    accepted = client.post(
        f"/api/teams/invitations/{invitation['id']}/accept",
        headers=_headers(invitee),
    )
    assert accepted.status_code == 200, accepted.get_json()

    # El entrenador recibe la notificación de aceptación.
    coach_history = client.get(
        "/api/notifications", headers=_headers(coach)
    ).get_json()
    assert [item["event_type"] for item in coach_history["notifications"]] == [
        "team.invitation.accepted"
    ]

    # El entrenador abandona el equipo: deja de ver notificaciones privadas
    # de ese equipo, pero su historial personal no se filtra a otros.
    left = client.post(
        f"/api/teams/{team.id}/leave", headers=_headers(coach)
    )
    assert left.status_code == 204, left.get_json()

    after_leave = client.get(
        "/api/notifications", headers=_headers(coach)
    ).get_json()
    assert after_leave["notifications"] == []
    assert after_leave["unread_count"] == 0

    # La invitación personal del recién unido sigue visible para él.
    invitee_history = client.get(
        "/api/notifications", headers=_headers(invitee)
    ).get_json()
    types = {item["event_type"] for item in invitee_history["notifications"]}
    assert "team.invitation.created" in types
    assert "team.invitation.accepted" not in types


def test_team_activity_history_is_members_only_and_paginated(app, client):
    captain = _user("activity-captain")
    coach = _user("activity-coach")
    outsider = _user("activity-outsider")
    outsider_team = _team("Outsider Team", "OUT")
    team = _team("Activity Team", "ACT")
    _member(team, captain, "CAPTAIN")
    _member(team, coach, "COACH")
    _member(outsider_team, outsider, "CAPTAIN")
    db.session.commit()

    invite = client.post(
        f"/api/teams/{team.id}/invitations",
        json={"user_id": outsider.id, "role": "PLAYER"},
        headers=_headers(captain),
    )
    # No se puede invitar a alguien que ya tiene equipo; se usa otro usuario.
    assert invite.status_code in (201, 409)

    # Genera actividad: cambio de rol y salida del entrenador.
    role = client.patch(
        f"/api/teams/{team.id}/members/{coach.id}",
        json={"role": "PLAYER"},
        headers=_headers(captain),
    )
    assert role.status_code == 200, role.get_json()

    leave = client.post(
        f"/api/teams/{team.id}/leave", headers=_headers(coach)
    )
    assert leave.status_code == 204, leave.get_json()

    history = client.get(
        f"/api/teams/{team.id}/activity?page=1&per_page=1",
        headers=_headers(captain),
    )
    assert history.status_code == 200, history.get_json()
    body = history.get_json()
    assert body["meta"]["total"] == 2
    assert body["meta"]["page"] == 1
    assert body["meta"]["per_page"] == 1
    assert len(body["activities"]) == 1
    # Más reciente primero: la salida ocurrió después del cambio de rol.
    assert body["activities"][0]["activity_type"] == "member.left"

    second_page = client.get(
        f"/api/teams/{team.id}/activity?page=2&per_page=1",
        headers=_headers(captain),
    ).get_json()
    assert second_page["activities"][0]["activity_type"] == "member.role_changed"
    assert second_page["activities"][0]["metadata"]["user_id"] == coach.id
    assert second_page["activities"][0]["actor"]["user_id"] == captain.id

    # El historial de actividad nunca se expone a quien no es integrante.
    forbidden = client.get(
        f"/api/teams/{team.id}/activity", headers=_headers(outsider)
    )
    assert forbidden.status_code == 403

    missing = client.get(
        "/api/teams/999999/activity", headers=_headers(captain)
    )
    assert missing.status_code == 404

    # Sin token tampoco.
    anonymous = client.get(f"/api/teams/{team.id}/activity")
    assert anonymous.status_code == 401


def test_activity_rows_never_generate_notifications(app, client):
    captain = _user("activity-notify-captain")
    invitee = _user("activity-notify-invitee")
    team = _team("Activity Notify", "AN")
    _member(team, captain, "CAPTAIN")
    db.session.commit()

    invitation = client.post(
        f"/api/teams/{team.id}/invitations",
        json={"user_id": invitee.id, "role": "PLAYER"},
        headers=_headers(captain),
    ).get_json()["invitation"]
    assert (
        client.post(
            f"/api/teams/invitations/{invitation['id']}/accept",
            headers=_headers(invitee),
        ).status_code
        == 200
    )

    assert db.session.query(TeamActivity).count() == 1
    assert db.session.query(TeamActivity).one().activity_type == "member.joined"
    # Solo la invitación y la aceptación generan notificación; la actividad no.
    types = {
        row.event_type for row in db.session.query(Notification).all()
    }
    assert types == {"team.invitation.created", "team.invitation.accepted"}


# --- Outbox transaccional ---------------------------------------------------


def _enable_outbox(app, *, max_attempts=3, backoff_base=1.0, backoff_max=60.0):
    app.config.update(
        REALTIME_ENABLED=True,
        REALTIME_OUTBOX_MAX_ATTEMPTS=max_attempts,
        REALTIME_OUTBOX_BACKOFF_BASE_SECONDS=backoff_base,
        REALTIME_OUTBOX_BACKOFF_MAX_SECONDS=backoff_max,
        REALTIME_OUTBOX_BATCH_SIZE=20,
    )


def _outbox_row(event_type="team.invitation.created"):
    return (
        db.session.query(RealtimeOutbox)
        .filter(RealtimeOutbox.event_type == event_type)
        .order_by(RealtimeOutbox.id.desc())
        .first()
    )


def _make_due(row):
    """Fuerza el vencimiento del backoff para ejecutar el relay ya."""
    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()
    db.session.expire_all()


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _invite(client, captain, invitee, team):
    return client.post(
        f"/api/teams/{team.id}/invitations",
        json={"user_id": invitee.id, "role": "PLAYER"},
        headers=_headers(captain),
    )


def _outbox_scenario(app):
    captain = _user("outbox-captain")
    invitee = _user("outbox-invitee")
    team = _team("Outbox Team", "OBX")
    _member(team, captain, "CAPTAIN")
    db.session.commit()
    return captain, invitee, team


def test_outbox_retries_with_exponential_backoff_then_delivers(
    app, client, monkeypatch
):
    _enable_outbox(app, max_attempts=5, backoff_base=2.0)
    captain, invitee, team = _outbox_scenario(app)

    calls = []
    outcomes = iter([False, False, True])

    def fake_publish(event):
        calls.append(event["event_id"])
        return next(outcomes, True)

    monkeypatch.setattr("app.realtime.client.publish_event", fake_publish)

    response = _invite(client, captain, invitee, team)
    assert response.status_code == 201, response.get_json()

    # Primer intento inmediato tras el commit: falla y queda pendiente.
    row = _outbox_row()
    assert row is not None
    assert row.status == "PENDING"
    assert row.attempts == 1
    assert row.last_error == "Realtime delivery failed"
    assert row.delivered_at is None
    first_delay = _aware(row.next_attempt_at) - _aware(row.created_at)
    assert 2.0 <= first_delay.total_seconds() < 7.0

    # Segundo intento: el backoff se duplica (base * 2^(attempts-1)).
    _make_due(row)
    assert run_once() == 1
    row = _outbox_row()
    assert row.status == "PENDING"
    assert row.attempts == 2
    second_delay = _aware(row.next_attempt_at) - datetime.now(timezone.utc)
    assert 3.0 <= second_delay.total_seconds() <= 5.0

    # Tercer intento: entregado; la outbox conserva el evento para auditoría.
    _make_due(row)
    assert run_once() == 1
    row = _outbox_row()
    assert row.status == "DELIVERED"
    assert row.attempts == 3
    assert row.delivered_at is not None
    assert row.last_error is None
    assert len(calls) == 3

    notification = db.session.query(Notification).one()
    assert notification.event_type == "team.invitation.created"
    assert db.session.query(NotificationRecipient).one().delivered_at is not None
    assert db.session.query(RealtimeOutbox).count() == 1


def test_outbox_marks_failed_after_max_attempts(app, client, monkeypatch):
    _enable_outbox(app, max_attempts=2, backoff_base=1.0)
    captain, invitee, team = _outbox_scenario(app)

    monkeypatch.setattr(
        "app.realtime.client.publish_event", lambda _event: False
    )

    response = _invite(client, captain, invitee, team)
    assert response.status_code == 201, response.get_json()

    row = _outbox_row()
    assert row.status == "PENDING"
    assert row.attempts == 1

    _make_due(row)
    assert run_once() == 1
    row = _outbox_row()
    assert row.status == "FAILED"
    assert row.attempts == 2
    assert row.last_error == "Realtime delivery failed"
    assert row.delivered_at is None

    # Un fallo permanente ya no vuelve a entrar en la cola de reintentos.
    assert run_once() == 0
    row = _outbox_row()
    assert row.status == "FAILED"
    assert row.attempts == 2

    # La notificación persistida sigue disponible para el historial offline.
    assert db.session.query(Notification).count() == 1
    assert db.session.query(NotificationRecipient).one().delivered_at is None


def test_run_once_processes_only_due_rows_and_respects_batch_limit(
    app, monkeypatch
):
    _enable_outbox(app, max_attempts=5)
    now = datetime.now(timezone.utc)
    due_ids = []
    for index in range(3):
        event_id = str(uuid.uuid4())
        due_ids.append(event_id)
        db.session.add(
            RealtimeOutbox(
                event_id=event_id,
                event_type="test.outbox",
                payload={"event_id": event_id, "event_type": "test.outbox"},
                status="PENDING",
                attempts=0,
                next_attempt_at=now - timedelta(seconds=10 - index),
                created_at=now,
            )
        )
    future_id = str(uuid.uuid4())
    db.session.add(
        RealtimeOutbox(
            event_id=future_id,
            event_type="test.outbox",
            payload={"event_id": future_id, "event_type": "test.outbox"},
            status="PENDING",
            attempts=0,
            next_attempt_at=now + timedelta(hours=1),
            created_at=now,
        )
    )
    db.session.commit()

    delivered = []

    def fake_publish(event):
        delivered.append(event["event_id"])
        return True

    monkeypatch.setattr("app.realtime.client.publish_event", fake_publish)

    assert run_once(limit=2) == 2
    assert delivered == due_ids[:2]

    assert run_once(limit=2) == 1
    assert set(delivered) == set(due_ids)

    # Ni las filas ya entregadas ni la futura se vuelven a intentar.
    assert run_once(limit=2) == 0
    future = (
        db.session.query(RealtimeOutbox)
        .filter(RealtimeOutbox.event_id == future_id)
        .one()
    )
    assert future.status == "PENDING"
    assert future.attempts == 0


def test_queue_event_rolls_back_notification_and_outbox_together(app):
    _enable_outbox(app)
    captain, invitee, team = _outbox_scenario(app)

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "team.invitation.created",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "resource_id": 1,
        "team_id": team.id,
        "actor": {"user_id": captain.id, "username": captain.username},
        "recipients": [invitee.id],
        "payload": {
            "invitation_id": 1,
            "team": {"id": team.id, "name": team.name, "tag": team.tag},
            "invited_by": {
                "user_id": captain.id,
                "username": captain.username,
            },
            "role": "PLAYER",
        },
    }

    queue_event(event)

    # Notificación, destinatarios y outbox comparten la MISMA transacción: no
    # hay commit intermedio dentro de queue_event.
    assert db.session.query(Notification).count() == 1
    assert db.session.query(NotificationRecipient).count() == 1
    assert db.session.query(RealtimeOutbox).count() == 1
    assert event["notification_id"] == db.session.query(Notification).one().id

    db.session.rollback()

    # Si la operación de negocio falla, no queda ni notificación ni outbox.
    assert db.session.query(Notification).count() == 0
    assert db.session.query(NotificationRecipient).count() == 0
    assert db.session.query(RealtimeOutbox).count() == 0
