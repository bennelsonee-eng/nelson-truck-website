"""
Cloudflare Access JWT validation.

The preview deployment (titantruckequipment.com) is fronted by Cloudflare Access.
Every request that reaches our origin through the tunnel carries a signed JWT in
the `Cf-Access-Jwt-Assertion` header (Cloudflare sets a `CF_Authorization` cookie
in the browser and converts it to that header at the edge on every request —
including the SPA's /api XHRs, which Vite forwards to us). We verify the JWT
against the team's public keys and check audience + issuer, then trust the
`email` claim as the authenticated tester's identity.

If `settings.cf_access_aud` is empty, validation is DISABLED and every call
returns None — so local dev and the Tailscale-only path (no Access in front)
are completely unaffected.

Cloudflare rotates the signing keys periodically, so the JWKS is cached with a
short TTL and force-refreshed once if a token references an unknown key id.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Header Cloudflare Access injects on every proxied request.
ACCESS_JWT_HEADER = "Cf-Access-Jwt-Assertion"

_JWKS_TTL_SECONDS = 600  # re-fetch the team's public keys every 10 minutes

_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0


@dataclass(frozen=True)
class CfIdentity:
    """An authenticated Cloudflare Access identity (a preview tester)."""

    email: str
    sub: str  # Cloudflare user UUID (stable per identity)
    raw: dict


def is_enabled() -> bool:
    """True when Cloudflare Access validation is configured (AUD present)."""
    s = get_settings()
    return bool(s.cf_access_aud and s.cf_access_team_domain)


def _issuer() -> str:
    return f"https://{get_settings().cf_access_team_domain}"


def _certs_url() -> str:
    return f"{_issuer()}/cdn-cgi/access/certs"


def _find_key(jwks: dict, kid: str | None) -> dict | None:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return k
    return None


async def _get_jwks(force: bool = False) -> dict | None:
    """Fetch + cache the team's JWKS. Returns None on network failure."""
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if not force and _jwks_cache is not None and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_certs_url())
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = now
    except Exception as exc:  # network / DNS / non-200 — fail closed (return None)
        logger.warning("Cloudflare Access JWKS fetch failed: %s", exc)
        return _jwks_cache  # may be a stale-but-usable cache, or None
    return _jwks_cache


async def verify_token(token: str | None) -> CfIdentity | None:
    """Validate a `Cf-Access-Jwt-Assertion` token.

    Returns a CfIdentity on success, or None for any failure (missing, expired,
    forged, wrong audience/issuer, or keys unreachable). Never raises — callers
    treat None as "not an authenticated tester".
    """
    if not token or not is_enabled():
        return None
    settings = get_settings()

    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError:
        return None

    jwks = await _get_jwks()
    if not jwks:
        return None
    key = _find_key(jwks, kid)
    if key is None:
        # Key id not found — Cloudflare may have rotated; refresh once.
        jwks = await _get_jwks(force=True)
        key = _find_key(jwks or {}, kid)
        if key is None:
            return None

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cf_access_aud,
            issuer=_issuer(),
        )
    except JWTError:
        return None

    email = (claims.get("email") or "").strip().lower()
    if not email:
        return None
    return CfIdentity(email=email, sub=claims.get("sub", ""), raw=claims)


async def verify_request(request) -> CfIdentity | None:
    """Pull the assertion header off a Starlette/FastAPI request and verify it."""
    return await verify_token(request.headers.get(ACCESS_JWT_HEADER))
