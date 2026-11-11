"""Integración de Flask con el servicio realtime (NestJS + Socket.IO)."""

from .events import (
    publish_invitation_accepted,
    publish_invitation_created,
    publish_invitation_rejected,
    publish_proposal_approved,
    publish_proposal_created,
    publish_proposal_rejected,
)
from .identity import realtime_internal_bp

__all__ = [
    "publish_invitation_accepted",
    "publish_invitation_created",
    "publish_invitation_rejected",
    "publish_proposal_approved",
    "publish_proposal_created",
    "publish_proposal_rejected",
    "realtime_internal_bp",
]
