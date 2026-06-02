# ADR 0003 — Pluggable authentication providers

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.12 (Phase 1)

## Context
Cloud uses email/password (OAuth-ready); on-prem will use Active Directory /
LDAP. Login logic must not be duplicated or hard-wired to one mechanism.

## Decision
Define an `AuthProvider` Protocol (`backend/app/auth/base.py`) with a single
`authenticate(db, username, password)` operation that returns the user on
success or `None` on invalid credentials. The existing Cost Calculator login is
wrapped as `EmailPasswordProvider` (`auth/email_password.py`) with no behaviour
change. A factory, `get_auth_provider()`, selects the implementation from
`settings.AUTH_PROVIDER`. The login route calls the provider rather than
verifying passwords inline.

## Consequences
- Adding LDAP/AD in Phase 3 is a new class behind the same Protocol — no route
  changes.
- `AUTH_PROVIDER=ldap` is recognised but raises `NotImplementedError` in Phase 1.
- A parallel `FileStore` Protocol (`backend/app/storage/base.py`) applies the
  same seam to file assets (drawings, DXFs, photos); concrete stores (network
  share, S3) arrive in Phase 3.
