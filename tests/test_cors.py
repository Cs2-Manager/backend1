"""CORS y registro de blueprints de la API.

Los preflights OPTIONS con 404 que se observaron no fueron un problema de
Flask: eran pedidos a un host/puerto equivocado (sin proxy, el frontend
apuntaba a ``localhost:5000``). Estos tests fijan el contrato real: todas las
rutas auditadas existen y responden el preflight correctamente.
"""

import pytest

# Endpoints del reporte "CORS Preflight Did Not Succeed — Status code: 404".
# Los protegidos responden el preflight sin token: los navegadores no envían
# credenciales en las solicitudes OPTIONS.
AUDITED_ENDPOINTS = [
    "/api/profile",
    "/api/teams/mine",
    "/api/teams/invitations",
    "/api/dashboard",
    "/api/players",
    "/api/teams",
]


@pytest.mark.parametrize("endpoint", AUDITED_ENDPOINTS)
def test_preflight_succeeds_for_every_audited_endpoint(client, endpoint):
    response = client.options(
        endpoint,
        headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost"


def test_preflight_does_not_authorize_unknown_origins(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://malicious.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    # El preflight se responde, pero sin permiso de CORS para ese origen.
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_health_endpoint_is_public(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json()["database"] == "ok"
