"""Comportamiento de Flask detrás del proxy inverso.

nginx es el único proxy confiable y normaliza X-Forwarded-For y
X-Forwarded-Proto; ProxyFix(x_for=1, x_proto=1) restituye la IP y el esquema
reales del cliente tomando el último valor de cada header (el que agregó
nginx). Sin proxy los headers no existen y la petición queda intacta.
"""

from flask import request


def _register_probe(app, route, captured):
    @app.get(route)
    def probe():  # pragma: no cover - el nombre importa poco al cliente
        captured["remote_addr"] = request.remote_addr
        captured["scheme"] = request.scheme
        return {"ok": True}


def test_proxyfix_restores_client_ip_and_scheme(app, client):
    captured = {}
    _register_probe(app, "/api/proxy-probe", captured)

    client.get(
        "/api/proxy-probe",
        headers={
            # El último valor es el que agregó nginx ($proxy_add_x_forwarded_for).
            "X-Forwarded-For": "203.0.113.7, 10.10.0.9",
            "X-Forwarded-Proto": "https",
        },
    )

    assert captured["remote_addr"] == "10.10.0.9"
    assert captured["scheme"] == "https"


def test_requests_without_proxy_headers_keep_local_values(app, client):
    captured = {}
    _register_probe(app, "/api/proxy-probe-local", captured)

    client.get("/api/proxy-probe-local")

    assert captured["remote_addr"] == "127.0.0.1"
    assert captured["scheme"] == "http"
