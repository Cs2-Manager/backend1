"""Regresión del secreto correcto en .env pero desactualizado en Docker."""

import json
import subprocess

from scripts import verify_faceit_oauth_runtime as runtime


def _settings():
    return {name: "configured-private-value" for name in runtime.OAUTH_SETTINGS}


def test_runtime_detects_stale_client_secret_without_revealing_it():
    expected = _settings()
    actual = {**expected, "FACEIT_OAUTH_CLIENT_SECRET": "stale-private-secret"}
    assert runtime.configuration_errors(expected, actual) == [
        "faceit_oauth_client_secret_configuration_drift"
    ]


def test_runtime_accepts_current_configuration():
    assert runtime.configuration_errors(_settings(), _settings()) == []


def test_runtime_rejects_missing_credentials():
    expected = {**_settings(), "FACEIT_OAUTH_CLIENT_SECRET": ""}
    assert runtime.configuration_errors(expected, expected) == [
        "faceit_oauth_client_secret_missing"
    ]


def test_cli_reports_drift_without_printing_docker_secrets(monkeypatch, capsys):
    expected = _settings()
    actual = {**expected, "FACEIT_OAUTH_CLIENT_SECRET": "stale-private-secret"}
    outputs = iter([
        json.dumps({"services": {"backend": {"environment": expected}}}),
        "backend-id\n",
        json.dumps([{"Config": {"Env": [f"{k}={v}" for k, v in actual.items()]}}]),
    ])
    monkeypatch.setattr(runtime, "_docker", lambda *_: next(outputs))
    assert runtime.main() == 1
    assert capsys.readouterr().out == (
        "http=none category=faceit_oauth_client_secret_configuration_drift\n"
    )


def test_cli_does_not_print_docker_errors(monkeypatch, capsys):
    def fail(*_):
        raise subprocess.CalledProcessError(
            1, ["docker"], stderr="private-client-secret"
        )

    monkeypatch.setattr(runtime, "_docker", fail)
    assert runtime.main() == 1
    assert capsys.readouterr().out == "http=none category=runtime_inspection_failed\n"
