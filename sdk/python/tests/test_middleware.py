"""Integration tests for auth_client SDK middleware and validator.

These tests use a mock JWKS server and test both the happy path and error cases.
They do NOT require a running auth service — JWKS is mocked.
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# ── Key generation for tests ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a fresh RSA-2048 key pair for tests."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem.decode(), public_pem.decode()


def _make_jwt(private_pem: str, sub: str, grants: list[str], expired: bool = False) -> str:
    """Create a test JWT using authlib.jose."""
    from authlib.jose import JsonWebKey, JsonWebSignature
    import json as _json

    key = JsonWebKey.import_key(private_pem.encode(), {"kty": "RSA"})
    now = int(time.time())
    exp = (now - 3600) if expired else (now + 900)
    payload = _json.dumps({"sub": sub, "grants": grants, "iat": now, "exp": exp}).encode()
    jws = JsonWebSignature()
    token: bytes = jws.serialize_compact({"alg": "RS256", "kid": "test-key-1"}, payload, key)
    return token.decode()


def _make_jwks(public_pem: str) -> dict:
    """Build a JWKS dict from a PEM public key."""
    from authlib.jose import JsonWebKey
    key = JsonWebKey.import_key(public_pem.encode(), {"kty": "RSA"})
    jwk = key.as_dict()
    jwk.update({"use": "sig", "alg": "RS256", "kid": "test-key-1"})
    return {"keys": [jwk]}


# ── Validator tests ───────────────────────────────────────────────────────────

def test_validate_token_success(rsa_keypair):
    """validate_token returns payload for a valid token with correct app grant."""
    private_pem, public_pem = rsa_keypair
    from auth_client import jwks_cache, validate_token
    jwks_cache.invalidate()

    token = _make_jwt(private_pem, sub="user-123", grants=["budget-site", "news-site"])
    mock_jwks = _make_jwks(public_pem)

    with patch("auth_client.jwks_cache._fetch_keys", return_value={
        k["kid"]: k for k in mock_jwks["keys"]
    }):
        payload = validate_token(token, "budget-site", "http://mock/jwks")

    assert payload["sub"] == "user-123"
    assert "budget-site" in payload["grants"]


def test_validate_token_expired(rsa_keypair):
    """validate_token raises TokenExpiredError for an expired token."""
    from auth_client import jwks_cache, validate_token
    from auth_client.exceptions import TokenExpiredError
    private_pem, public_pem = rsa_keypair
    jwks_cache.invalidate()

    token = _make_jwt(private_pem, sub="user-123", grants=["budget-site"], expired=True)
    mock_jwks = _make_jwks(public_pem)

    with patch("auth_client.jwks_cache._fetch_keys", return_value={
        k["kid"]: k for k in mock_jwks["keys"]
    }):
        with pytest.raises(TokenExpiredError):
            validate_token(token, "budget-site", "http://mock/jwks")


def test_validate_token_no_grant(rsa_keypair):
    """validate_token raises NoGrantError when app not in grants."""
    from auth_client import jwks_cache, validate_token
    from auth_client.exceptions import NoGrantError
    private_pem, public_pem = rsa_keypair
    jwks_cache.invalidate()

    token = _make_jwt(private_pem, sub="user-123", grants=["news-site"])
    mock_jwks = _make_jwks(public_pem)

    with patch("auth_client.jwks_cache._fetch_keys", return_value={
        k["kid"]: k for k in mock_jwks["keys"]
    }):
        with pytest.raises(NoGrantError) as exc_info:
            validate_token(token, "budget-site", "http://mock/jwks")
    assert exc_info.value.app_name == "budget-site"


def test_validate_token_invalid_signature(rsa_keypair):
    """validate_token raises InvalidTokenError for a tampered token."""
    from auth_client import jwks_cache, validate_token
    from auth_client.exceptions import InvalidTokenError
    private_pem, public_pem = rsa_keypair
    jwks_cache.invalidate()

    # Use different key for signing vs verification
    other_private = rsa.generate_private_key(65537, 2048)
    other_private_pem = other_private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    token = _make_jwt(other_private_pem, sub="user-123", grants=["budget-site"])
    mock_jwks = _make_jwks(public_pem)  # correct public key, wrong signing key

    with patch("auth_client.jwks_cache._fetch_keys", return_value={
        k["kid"]: k for k in mock_jwks["keys"]
    }):
        with pytest.raises(InvalidTokenError):
            validate_token(token, "budget-site", "http://mock/jwks")
