"""JWT signing, verification, and JWKS endpoint payload generation.

Uses authlib.jose with RS256 (per ADR-003). Private key loaded from settings.
python-jose is intentionally NOT used (CVE exposure, unmaintained since 2022).

authlib.jose.jwt is used for encode/decode (handles registered claims like exp/iat
automatically). JsonWebKey is used for key loading and JWKS serialisation.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from authlib.jose import JsonWebKey, jwt as jose_jwt
from authlib.jose.errors import JoseError

from src.config import settings


class JWTError(Exception):
    """Raised on JWT decode/verify failure."""


# ── Key loading (cached module-level) ────────────────────────────────────────

_private_key: Any = None
_public_key: Any = None


def _get_private_key() -> Any:
    global _private_key
    if _private_key is None:
        _private_key = JsonWebKey.import_key(
            settings.jwt_private_key.encode(), {"kty": "RSA"}
        )
    return _private_key


def _get_public_key() -> Any:
    global _public_key
    if _public_key is None:
        _public_key = JsonWebKey.import_key(
            settings.jwt_public_key.encode(), {"kty": "RSA"}
        )
    return _public_key


# ── Token issuance ────────────────────────────────────────────────────────────


def create_access_token(sub: str, grants: list[str]) -> str:
    """Sign an RS256 JWT access token and return the compact serialization."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.access_token_ttl_minutes)

    header = {"alg": "RS256", "kid": settings.jwt_key_id}
    payload: dict[str, Any] = {
        "sub": sub,
        "grants": grants,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    token: bytes = jose_jwt.encode(header, payload, _get_private_key())
    return token.decode()


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify RS256 signature, expiry, and return the decoded payload dict.

    Raises JWTError on any verification failure.
    authlib.jose.jwt.decode validates the signature and raises JoseError on failure.
    We additionally check exp manually for a clear error message.
    """
    try:
        claims = jose_jwt.decode(token, _get_public_key())
        claims.validate_exp()  # raises JoseError if expired
        payload: dict[str, Any] = dict(claims)
    except JoseError as exc:
        raise JWTError(str(exc)) from exc
    except Exception as exc:
        raise JWTError(str(exc)) from exc

    return payload


# ── Refresh token helpers ─────────────────────────────────────────────────────


def generate_refresh_token() -> str:
    """Generate a cryptographically random opaque refresh token (256-bit hex)."""
    return secrets.token_hex(32)


def hash_refresh_token(token: str) -> str:
    """Return sha256 hex of the opaque token (used as Redis/DB key)."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── JWKS ──────────────────────────────────────────────────────────────────────


def get_jwks_payload() -> dict:
    """Build the JWK Set payload for /.well-known/jwks.json."""
    key = _get_public_key()
    # authlib RSAKey exposes as_dict() with standard JWK fields
    jwk_dict = key.as_dict()
    jwk_dict.update(
        {
            "use": "sig",
            "alg": "RS256",
            "kid": settings.jwt_key_id,
        }
    )
    return {"keys": [jwk_dict]}


