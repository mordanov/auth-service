"""JWT RS256 validator using authlib.jose."""
from __future__ import annotations

import json
import time
from typing import Any

from authlib.jose import JsonWebKey, JsonWebSignature
from authlib.jose.errors import JoseError

from auth_client.exceptions import InvalidTokenError, NoGrantError, TokenExpiredError
from auth_client.jwks_cache import get_key


def validate_token(token: str, app_name: str, jwks_url: str) -> dict[str, Any]:
    """Validate an RS256 JWT access token and verify the app_name grant.

    Returns the decoded payload dict on success.
    Raises TokenExpiredError, InvalidTokenError, or NoGrantError on failure.
    """
    # 1. Extract header to get kid (without full verification yet)
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenError("Malformed JWT: expected 3 parts")
        # Decode header
        import base64
        header_data = parts[0]
        # Add padding
        padding = 4 - len(header_data) % 4
        if padding != 4:
            header_data += "=" * padding
        header = json.loads(base64.urlsafe_b64decode(header_data))
        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("JWT header missing kid")
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("Cannot parse JWT header") from exc

    # 2. Fetch public key from JWKS cache
    jwk_dict = get_key(jwks_url, kid)

    # 3. Verify signature using authlib
    try:
        key = JsonWebKey.import_key(jwk_dict)
        jws = JsonWebSignature()
        data = jws.deserialize_compact(token.encode(), key)
        payload = json.loads(data["payload"])
    except JoseError as exc:
        raise InvalidTokenError(f"JWT signature verification failed: {exc}") from exc
    except Exception as exc:
        raise InvalidTokenError(f"JWT decode error: {exc}") from exc

    # 4. Check expiry
    exp = payload.get("exp", 0)
    if exp < int(time.time()):
        raise TokenExpiredError()

    # 5. Check app grant
    grants: list[str] = payload.get("grants", [])
    if app_name not in grants:
        raise NoGrantError(app_name)

    return payload
