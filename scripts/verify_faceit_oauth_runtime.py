"""Detecta configuración OAuth desactualizada sin mostrar valores sensibles.

Ejecutar desde cualquier directorio:
    python back/scripts/verify_faceit_oauth_runtime.py

Solo consulta Compose y el contenedor; no inicia OAuth ni modifica servicios.
"""

import hmac
import json
from pathlib import Path
import subprocess


BACKEND_DIR = Path(__file__).resolve().parents[1]
OAUTH_SETTINGS = (
    "FACEIT_OAUTH_CLIENT_ID",
    "FACEIT_OAUTH_CLIENT_SECRET",
    "FACEIT_OAUTH_REDIRECT_URI",
    "FACEIT_PUBLIC_BASE_URL",
    "FACEIT_OAUTH_TOKEN_URL",
    "FACEIT_OAUTH_USERINFO_URL",
    "FACEIT_OAUTH_AUTHORIZE_URL",
    "FACEIT_OAUTH_SCOPES",
)


def configuration_errors(expected, actual):
    errors = []
    for name in OAUTH_SETTINGS:
        wanted = str(expected.get(name) or "")
        running = str(actual.get(name) or "")
        if not wanted.strip():
            errors.append(f"{name.lower()}_missing")
        elif not hmac.compare_digest(wanted.encode(), running.encode()):
            errors.append(f"{name.lower()}_configuration_drift")
    return errors


def _docker(*args):
    return subprocess.run(
        ["docker", *args], cwd=BACKEND_DIR,
        check=True, capture_output=True, text=True,
    ).stdout


def main():
    try:
        desired = json.loads(_docker("compose", "config", "--format", "json"))
        container_id = _docker("compose", "ps", "-q", "backend").strip()
        if not container_id or "\n" in container_id:
            print("http=none category=backend_container_not_unique_or_running")
            return 1
        container = json.loads(_docker("inspect", container_id))[0]
        running = dict(item.split("=", 1) for item in container["Config"]["Env"])
        errors = configuration_errors(
            desired["services"]["backend"]["environment"], running
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        # stderr de Compose/inspect podría incluir configuración. No publicarlo.
        print("http=none category=runtime_inspection_failed")
        return 1
    for category in errors:
        print(f"http=none category={category}")
    if not errors:
        print("http=none category=oauth_runtime_configuration_matches")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
