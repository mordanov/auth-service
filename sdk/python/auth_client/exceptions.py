"""Exceptions raised by the auth-client SDK."""


class AuthError(Exception):
    """Base exception for all auth-client errors.

    Attributes:
        code: Machine-readable error code (e.g. 'token_expired').
    """

    def __init__(self, message: str, code: str = "auth_error") -> None:
        super().__init__(message)
        self.code = code


class TokenExpiredError(AuthError):
    """Raised when the supplied JWT has expired."""

    def __init__(self, message: str = "Token has expired") -> None:
        super().__init__(message, code="token_expired")


class InvalidTokenError(AuthError):
    """Raised when the supplied JWT is malformed or its signature is invalid."""

    def __init__(self, message: str = "Token is invalid") -> None:
        super().__init__(message, code="invalid_token")


class NoGrantError(AuthError):
    """Raised when the token lacks a required app grant."""

    def __init__(self, app_name: str) -> None:
        super().__init__(f"No grant for app: {app_name}", code="no_grant")
        self.app_name = app_name
