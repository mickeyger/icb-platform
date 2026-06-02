"""Shared service-layer exceptions (WO v4.15, ADR 0008).

Reuses v4.14's ServiceError / NotFoundError base (defined in production_jobs) and
adds InvalidStateError for the Materials/Buying/Stores 422 cases (raise twice,
resolve twice, defer-after-raise, raise-discrepancy on a non-discrepancy count).
Routers translate these to HTTPException.
"""
from app.services.production_jobs import NotFoundError, ServiceError


class InvalidStateError(ServiceError):
    """An action is invalid for the entity's current state (-> 422)."""


__all__ = ["ServiceError", "NotFoundError", "InvalidStateError"]
