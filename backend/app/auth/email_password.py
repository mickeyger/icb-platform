"""Email/username + password authentication.

This is the existing Cost Calculator login (passlib bcrypt verification against
User.password_hash), now expressed behind the AuthProvider Protocol. No
behaviour change — the login route delegates here.
"""
from __future__ import annotations

from typing import Optional

from ..database import User
from ..deps import pwd_context
from .base import AuthProvider


class EmailPasswordProvider:
    name = "email_password"

    def authenticate(self, db, username: str, password: str) -> Optional[User]:
        user = db.query(User).filter_by(username=username).first()
        if not user or not pwd_context.verify(password, user.password_hash):
            return None
        return user


# Static assurance that the implementation satisfies the Protocol.
_check: AuthProvider = EmailPasswordProvider()
