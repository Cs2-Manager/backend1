"""Pruebas de configuración de SECRET_KEY y seguridad de secretos.

Cubren:
- Clave válida desde variable de entorno (≥ 32 bytes).
- Clave demasiado corta desde variable de entorno.
- Clave ausente en desarrollo (valor aleatorio con advertencia).
- Clave ausente en producción (error claro).
- Clave desde archivo (SECRET_KEY_FILE).
- Valor generado no predecible.
"""

import os

import pytest

from app.config import _detect_environment, _resolve_secret_key


def test_detect_environment_production(monkeypatch):
    """APP_ENV=production se detecta como entorno de producción."""
    monkeypatch.setenv("APP_ENV", "production")
    assert _detect_environment() == "production"


def test_detect_environment_production_alias(monkeypatch):
    """APP_ENV=prod también se detecta como producción."""
    monkeypatch.setenv("APP_ENV", "prod")
    assert _detect_environment() == "production"


def test_detect_environment_development(monkeypatch):
    """APP_ENV=development se detecta como entorno de desarrollo."""
    monkeypatch.setenv("APP_ENV", "development")
    assert _detect_environment() == "development"


def test_detect_environment_default_is_development(monkeypatch):
    """Sin variables de entorno, el entorno por defecto es desarrollo."""
    for var in ("APP_ENV", "FLASK_ENV", "ENV"):
        monkeypatch.delenv(var, raising=False)
    assert _detect_environment() == "development"


def test_secret_key_from_env_long_enough(monkeypatch):
    """SECRET_KEY definida en el entorno con ≥ 32 bytes se usa tal cual."""
    monkeypatch.setenv("SECRET_KEY", "a" * 40)
    assert _resolve_secret_key() == "a" * 40


def test_secret_key_from_env_short_warns(monkeypatch):
    """SECRET_KEY definida con < 32 bytes en desarrollo emite advertencia."""
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    with pytest.warns(UserWarning, match="menos de 32 bytes"):
        assert _resolve_secret_key() == "short"


def test_secret_key_from_env_short_in_production_raises(monkeypatch):
    """SECRET_KEY corta en producción lanza RuntimeError claro."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="menos de 32 bytes"):
        _resolve_secret_key()


def test_secret_key_missing_in_production_raises(monkeypatch):
    """SECRET_KEY ausente en producción lanza RuntimeError claro."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    with pytest.raises(
        RuntimeError, match="SECRET_KEY no está definida"
    ):
        _resolve_secret_key()


def test_secret_key_from_secret_file(monkeypatch, tmp_path):
    """SECRET_KEY_FILE se lee cuando no hay variable de entorno directa."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    secret_file = tmp_path / "flask_secret.key"
    secret_file.write_text("clave-de-prueba-con-mas-de-32-bytes-xyz")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_file))
    assert _resolve_secret_key() == "clave-de-prueba-con-mas-de-32-bytes-xyz"


def test_secret_key_file_missing_is_ignored(monkeypatch):
    """SECRET_KEY_FILE que apunta a archivo inexistente no rompe."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY_FILE", "/ruta/que/no/existe.key")
    with pytest.warns(UserWarning, match="aleatorio temporal"):
        key = _resolve_secret_key()
    assert len(key.encode("utf-8")) >= 32


def test_secret_key_not_defined_generates_random(monkeypatch):
    """Sin SECRET_KEY definida en desarrollo, se genera valor aleatorio."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    with pytest.warns(UserWarning, match="aleatorio temporal"):
        key = _resolve_secret_key()
    assert len(key.encode("utf-8")) >= 32


def test_generated_secret_is_not_predictable(monkeypatch):
    """El valor generado no es un placeholder obvio."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    with pytest.warns(UserWarning):
        key = _resolve_secret_key()
    assert "changeme" not in key.lower()
    assert "example" not in key.lower()
    assert "placeholder" not in key.lower()
    assert "your_" not in key.lower()
    assert key != "dev-secret-key"
    assert len(key) == 64  # token_hex(32) = 64 caracteres hex


def test_secret_key_prefixed_with_spaces_is_stripped(monkeypatch):
    """Espacios alrededor del valor en SECRET_KEY se eliminan."""
    monkeypatch.setenv("SECRET_KEY", "  " + "a" * 40 + "  ")
    assert _resolve_secret_key() == "a" * 40
