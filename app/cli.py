"""Comandos administrativos de la aplicación."""

import click

from app.extensions import db
from app.models.user import User


def _find_user(identifier):
    identifier = identifier.strip()
    return (
        db.session.query(User)
        .filter((User.username == identifier) | (User.email == identifier.lower()))
        .first()
    )


def register_cli(app):
    @app.cli.command("set-admin")
    @click.argument("identifier")
    @click.option("--revoke", is_flag=True, help="Quita el permiso de administrador.")
    def set_admin(identifier, revoke):
        """Designa o revoca un administrador por username o email."""
        user = _find_user(identifier)
        if user is None:
            raise click.ClickException(f"No existe un usuario con '{identifier}'.")

        user.is_admin = not revoke
        db.session.commit()
        action = "revocado" if revoke else "otorgado"
        click.echo(f"Permiso de administrador {action} para {user.username}.")
