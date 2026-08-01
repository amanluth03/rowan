"""In-process JWT harness: an ephemeral RSA keypair plus a JWKS document.

Lets the whole auth suite run with no secrets, no network, and no live
Supabase project. Keys are generated per-process and never persisted.
"""

from __future__ import annotations

import time
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

TEST_ISSUER = "https://test.supabase.co/auth/v1"
TEST_AUDIENCE = "authenticated"
_KID = "test-key-1"


class JwtHarness:
    def __init__(self) -> None:
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
            self._private_key.public_key(), as_dict=True
        )
        self._jwk.update({"kid": _KID, "use": "sig", "alg": "RS256"})

    def jwks_dict(self) -> dict:
        return {"keys": [self._jwk]}

    def mint(
        self,
        sub: UUID | str,
        email: str = "user@example.com",
        *,
        issuer: str = TEST_ISSUER,
        audience: str = TEST_AUDIENCE,
        expires_in: int = 3600,
        algorithm: str = "RS256",
        kid: str = _KID,
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": str(sub),
            "email": email,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(
            payload, self._private_key, algorithm=algorithm, headers={"kid": kid}
        )

    def mint_unsigned(self, sub: UUID | str) -> str:
        """An `alg: none` token -- the classic verification bypass."""
        now = int(time.time())
        payload = {
            "sub": str(sub), "iss": TEST_ISSUER, "aud": TEST_AUDIENCE,
            "iat": now, "exp": now + 3600,
        }
        return jwt.encode(payload, key="", algorithm="none")
