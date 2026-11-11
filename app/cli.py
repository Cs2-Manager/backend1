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

    @app.cli.command("steam-sync")
    @click.option(
        "--identifier",
        default=None,
        help="Username o email de un usuario concreto (opcional).",
    )
    def steam_sync(identifier):
        """Sincroniza los datos de Steam de una cuenta o de todas."""
        from app.models.steam import SteamAccount
        from app.services import steam_service

        query = db.session.query(SteamAccount)
        if identifier:
            query = query.join(User, SteamAccount.user_id == User.id).filter(
                (User.username == identifier)
                | (User.email == identifier.lower())
            )
        accounts = query.order_by(SteamAccount.id).all()
        if not accounts:
            click.echo("No hay cuentas de Steam para sincronizar.")
            return

        for account in accounts:
            result = steam_service.sync_account(account.user)
            sync = result["sync"]
            click.echo(
                f"{account.user.username}: {sync['status']} - "
                f"{sync.get('message', '')}"
            )

    @app.cli.command("faceit-sync")
    @click.option(
        "--identifier",
        default=None,
        help="Username o email de un usuario concreto (opcional).",
    )
    @click.option(
        "--force",
        is_flag=True,
        help="Ignora el intervalo mínimo entre sincronizaciones.",
    )
    def faceit_sync(identifier, force):
        """Sincroniza estadísticas verificadas de FACEIT."""
        from app.models.faceit import FaceitAccount
        from app.services import faceit_service

        query = db.session.query(FaceitAccount)
        if identifier:
            query = query.join(User, FaceitAccount.user_id == User.id).filter(
                (User.username == identifier)
                | (User.email == identifier.lower())
            )
        accounts = query.order_by(FaceitAccount.id).all()
        if not accounts:
            click.echo("No hay cuentas de FACEIT para sincronizar.")
            return

        for account in accounts:
            result = faceit_service.sync(account.user, force=force)
            sync = result.get("sync", {})
            click.echo(
                f"{account.user.username}: {sync.get('status', 'ERROR')} - "
                f"{result.get('message', '')}"
            )

    @app.cli.command("matchmaking-worker")
    @click.option(
        "--once",
        is_flag=True,
        help="Ejecuta una sola pasada y termina (útil en CI o mantenimiento).",
    )
    def matchmaking_worker(once):
        """Procesa demos y sincronizaciones de matchmaking de CS2."""
        from app.worker import matchmaking as worker

        if once:
            click.echo(worker.run_once())
            return

        click.echo("Worker de matchmaking iniciado. Ctrl+C para detener.")
        try:
            worker.run_forever()
        except KeyboardInterrupt:
            click.echo("Worker detenido.")

    @app.cli.command("matchmaking-sync")
    @click.option(
        "--identifier",
        default=None,
        help="Username o email de un usuario concreto (opcional).",
    )
    def matchmaking_sync(identifier):
        """Descubre share codes nuevos para autorizaciones activas."""
        from app.models.matchmaking import MatchmakingAuthorization
        from app.worker import matchmaking as worker

        query = (
            db.session.query(MatchmakingAuthorization)
            .join(User, MatchmakingAuthorization.user_id == User.id)
            .filter(MatchmakingAuthorization.status == "ACTIVE")
        )
        if identifier:
            query = query.filter(
                (User.username == identifier)
                | (User.email == identifier.lower())
            )
        authorizations = query.order_by(MatchmakingAuthorization.id).all()
        if not authorizations:
            click.echo("No hay autorizaciones activas para sincronizar.")
            return

        for authorization in authorizations:
            outcome = worker.discover_authorization(authorization)
            click.echo(
                f"{authorization.user.username}: {outcome.status} - "
                f"{outcome.found} código(s) nuevo(s)"
                + (f" ({outcome.error})" if outcome.error else "")
            )

    @app.cli.command("realtime-outbox-flush")
    @click.option(
        "--limit",
        type=int,
        default=100,
        show_default=True,
        help="Máximo de eventos pendientes a reintentar.",
    )
    def realtime_outbox_flush(limit):
        """Reintenta las entregas pendientes de la outbox de realtime."""
        from app.notifications.outbox import run_once

        attempted = run_once(limit=limit)
        click.echo(f"Eventos intentados: {attempted}")
