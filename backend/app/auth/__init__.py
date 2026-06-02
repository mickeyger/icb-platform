"""Authentication provider factory.

Selects the active AuthProvider from settings.AUTH_PROVIDER. Phase 1 implements
only 'email_password'; 'ldap' is a recognised but Phase 3 feature (stub).
"""
from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import AuthProvider
from .email_password import EmailPasswordProvider

__all__ = ["AuthProvider", "EmailPasswordProvider", "get_auth_provider"]


@lru_cache(maxsize=1)
def get_auth_provider() -> AuthProvider:
    provider = settings.AUTH_PROVIDER.strip().lower()
    if provider == "email_password":
        return EmailPasswordProvider()
    if provider == "ldap":
        raise NotImplementedError(
            "AUTH_PROVIDER=ldap is a Phase 3 feature; only 'email_password' is "
            "active in Phase 1."
        )
    raise ValueError(f"Unknown AUTH_PROVIDER: {settings.AUTH_PROVIDER!r}")
