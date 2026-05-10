"""auth-client — SDK for validating auth service JWTs in client applications."""
from auth_client.exceptions import AuthError, InvalidTokenError, NoGrantError, TokenExpiredError
from auth_client.middleware import AuthMiddleware, AuthenticatedUser, get_auth_dependency
from auth_client.validator import validate_token

__all__ = [
    "AuthMiddleware",
    "AuthenticatedUser",
    "AuthError",
    "InvalidTokenError",
    "NoGrantError",
    "TokenExpiredError",
    "get_auth_dependency",
    "validate_token",
]
