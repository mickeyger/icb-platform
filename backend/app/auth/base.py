"""Pluggable authentication provider interface (WO v4.12).

Phase 1 ships a single active provider — EmailPasswordProvider, which wraps the
existing Cost Calculator login with no behaviour change. The LDAP/AD provider is
a Phase 3 stub. The active provider is chosen by settings.AUTH_PROVIDER via
app.auth.get_auth_provider().
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Verify credentials against a backing store.

    Implementations return the authenticated user record on success or ``None``
    on invalid credentials. Infrastructure failures (e.g. the database being
    unreachable) propagate as exceptions for the caller to handle.
    """

    name: str

    def authenticate(self, db, username: str, password: str) -> Optional[object]:
        ...
