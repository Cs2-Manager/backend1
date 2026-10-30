"""Servicio de dashboard.

Proporciona datos básicos para el panel de control.
"""


def get_dashboard():
    """Retorna información básica del dashboard."""
    return {
        "total_teams": 0,
        "total_players": 0,
        "recent_activity": [],
    }
