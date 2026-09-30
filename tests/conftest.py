"""Shared test fixtures / environment.

Sets a deterministic dev PHI key and test DB URLs BEFORE any rcm module imports
settings, so crypto and config tests run with a valid, fail-closed key present.
"""

from __future__ import annotations

import base64
import os

# A fixed 32-byte key for tests (base64url). Never a real key.
os.environ.setdefault(
    "RCM_MASTER_KEY",
    # exactly 32 bytes -> AES-256 key
    base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode(),
)
os.environ.setdefault("RCM_ENV", "test")
os.environ.setdefault("RCM_EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("RCM_EMBEDDING_DIM", "64")
