from fastapi import APIRouter
from backend.src.services.token_service import get_jwks_payload

router = APIRouter(tags=["discovery"])


@router.get("/.well-known/jwks.json", response_model=None)
async def jwks() -> dict:
    """Return the JSON Web Key Set (public keys for JWT verification)."""
    return get_jwks_payload()
