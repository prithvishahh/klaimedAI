"""Application-level PHI encryption at rest (AES-256-GCM).

Every PHI value stored in Postgres (patient name, DOB, chart text, ...) is
encrypted here before it touches the database, and decrypted only when the
application legitimately needs the cleartext. The database never sees plaintext
PHI, so a database compromise alone does not disclose PHI.

Design:
  * AES-256-GCM (AEAD) — confidentiality + integrity in one primitive.
  * Fresh random 96-bit nonce per value; token = base64url(nonce || ct || tag).
  * The key comes from ``RCM_MASTER_KEY`` (fail-closed — no key, no start).
  * In production ``RCM_MASTER_KEY`` is a KMS-wrapped data key (true envelope
    encryption); locally it is a base64url dev key. The interface is identical.

The ``EncryptedString`` SQLAlchemy type applies this transparently to a column.

CLI:  python -m rcm.core.crypto keygen   # print a fresh dev master key
"""

from __future__ import annotations

import base64
import os
import sys
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # 96-bit GCM nonce (recommended)


class CryptoError(Exception):
    """Raised on any encryption/decryption or key-material failure."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def generate_key() -> str:
    """Return a fresh base64url-encoded 256-bit master key (for dev/keygen)."""
    return _b64url_encode(os.urandom(_KEY_BYTES))


def _decode_master_key(encoded: str) -> bytes:
    try:
        key = _b64url_decode(encoded)
    except Exception as exc:  # noqa: BLE001 - normalize to CryptoError
        raise CryptoError("RCM_MASTER_KEY is not valid base64url") from exc
    if len(key) != _KEY_BYTES:
        raise CryptoError(
            f"RCM_MASTER_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}"
        )
    return key


@lru_cache(maxsize=1)
def _cipher() -> AESGCM:
    """Build the AES-GCM cipher from settings. Fail-closed if the key is absent."""
    from rcm.core.config import get_settings

    return AESGCM(_decode_master_key(get_settings().master_key))


def encrypt(plaintext: str, *, aad: bytes | None = None) -> str:
    """Encrypt ``plaintext`` -> base64url token (nonce || ciphertext || tag).

    ``aad`` (associated data) is authenticated but not encrypted; pass a stable
    context value (e.g. a column name) to bind ciphertext to its location.
    """
    if plaintext is None:  # defensive; callers should pass "" not None
        raise CryptoError("cannot encrypt None")
    nonce = os.urandom(_NONCE_BYTES)
    ct = _cipher().encrypt(nonce, plaintext.encode("utf-8"), aad)
    return _b64url_encode(nonce + ct)


def decrypt(token: str, *, aad: bytes | None = None) -> str:
    """Decrypt a token produced by :func:`encrypt`. Raises on tamper/wrong key."""
    raw = _b64url_decode(token)
    if len(raw) <= _NONCE_BYTES:
        raise CryptoError("ciphertext token too short")
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        return _cipher().decrypt(nonce, ct, aad).decode("utf-8")
    except InvalidTag as exc:
        raise CryptoError("decryption failed: bad key or tampered ciphertext") from exc


def _main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "keygen":
        print(generate_key())
        return 0
    print("usage: python -m rcm.core.crypto keygen", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
