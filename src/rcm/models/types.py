"""Custom SQLAlchemy column types.

``EncryptedString`` transparently encrypts a value on the way into the database
and decrypts on the way out, using the AES-256-GCM primitive in
``rcm.core.crypto``. The database column only ever holds ciphertext, so PHI is
encrypted at rest without callers having to remember to encrypt.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

from rcm.core import crypto


class EncryptedString(TypeDecorator[str]):
    """A Text column whose Python value is plaintext but storage is ciphertext.

    ``None`` passes through untouched (NULL stays NULL). The stored form is the
    base64url AEAD token from :func:`rcm.core.crypto.encrypt`.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return crypto.encrypt(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return crypto.decrypt(value)


# Re-export for convenience in models.
__all__ = ["EncryptedString", "String"]
