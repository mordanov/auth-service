"""Token validation utilities — stub (to be implemented in Phase 2)."""

from __future__ import annotations


def validate_token(token: str, public_key: str, algorithms: list[str] | None = None) -> dict:
    """Validate a JWT and return its decoded claims.

    Raises:
        TokenExpiredError: if the token has expired.
        InvalidTokenError: if the token signature or structure is invalid.
    """
    raise NotImplementedError("validate_token will be implemented in Phase 2")
