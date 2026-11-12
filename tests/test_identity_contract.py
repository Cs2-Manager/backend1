"""Internal auth error precedence and replay protection are HTTP contracts."""
import time
import uuid

import pytest

from app.realtime.signature import sign


def signed_headers(app, body):
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    return {
        "Content-Type": "application/json",
        "X-Realtime-Timestamp": timestamp,
        "X-Realtime-Nonce": nonce,
        "X-Realtime-Signature": sign(app.config["REALTIME_HMAC_SECRET"], timestamp, nonce, body),
    }


@pytest.mark.parametrize("body,message", [
    (b'not json', "Invalid JSON body"), (b'\xff', "Invalid JSON body"),
    (b'[]', "Invalid JSON body"), (b'null', "Invalid JSON body"),
    (b'{}', "Invalid user_id"), (b'{"user_id":true}', "Invalid user_id"),
    (b'{"user_id":"1"}', "Invalid user_id"), (b'{"user_id":0}', "Invalid user_id"),
])
def test_signed_invalid_payload_consumes_nonce(app, client, body, message):
    headers = signed_headers(app, body)
    response = client.post("/internal/realtime/identity", data=body, headers=headers)
    assert (response.status_code, response.get_json()) == (400, {"error": message})
    replay = client.post("/internal/realtime/identity", data=body, headers=headers)
    assert (replay.status_code, replay.get_json()) == (401, {"error": "Internal request replayed"})


def test_authentication_precedes_json_parsing(client):
    response = client.post("/internal/realtime/identity", data=b'not json')
    assert (response.status_code, response.get_json()) == (401, {"error": "Missing internal authentication headers"})


def test_missing_credentials_precede_invalid_window_configuration(app, client):
    app.config["REALTIME_IDENTITY_MAX_AGE_SECONDS"] = "invalid"
    response = client.post("/internal/realtime/identity", data=b'{}')
    assert (response.status_code, response.get_json()) == (401, {"error": "Missing internal authentication headers"})


@pytest.mark.parametrize("header,value,message", [
    ("X-Realtime-Timestamp", "invalid", "Invalid internal timestamp"),
    ("X-Realtime-Nonce", "short", "Invalid internal nonce"),
    ("X-Realtime-Signature", "wrong", "Invalid internal signature"),
])
def test_internal_authentication_error_messages(app, client, header, value, message):
    body = b'{"user_id":1}'
    headers = signed_headers(app, body)
    headers[header] = value
    response = client.post("/internal/realtime/identity", data=body, headers=headers)
    assert (response.status_code, response.get_json()) == (401, {"error": message})
