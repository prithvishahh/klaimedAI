"""PHI de-identification for model calls (fail-closed).

Before ANY text is sent to a model, structured identifiers are stripped and the
result is checked. If residual PHI is still detectable, we refuse to send —
fail-closed. This is a hard boundary: PHI must never leave the BAA-covered
environment inside a prompt, and prompt bodies are never logged.

Phase 0 targets structured identifiers (SSN, phone, email, dates, long ID runs)
plus caller-supplied patient names. A later phase can add clinical NER; the
fail-closed contract stays the same.
"""

from __future__ import annotations

import re

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)
_LONG_ID = re.compile(r"\b\d{7,}\b")  # member/account/claim numbers


class PHILeakError(Exception):
    """Raised when text still contains detectable PHI and must not be sent."""


def deidentify(text: str, names: tuple[str, ...] = ()) -> str:
    """Return a de-identified copy of ``text``.

    ``names`` are caller-supplied patient/subscriber names to redact by literal
    match (from the record being processed).
    """
    out = text
    for name in names:
        name = name.strip()
        if name:
            out = re.sub(re.escape(name), "[NAME]", out, flags=re.IGNORECASE)
    out = _SSN.sub("[SSN]", out)
    out = _EMAIL.sub("[EMAIL]", out)
    out = _PHONE.sub("[PHONE]", out)
    out = _DATE.sub("[DATE]", out)
    out = _LONG_ID.sub("[ID]", out)
    return out


def residual_phi(text: str) -> list[str]:
    """Return the kinds of structured PHI still present (empty = clean)."""
    found: list[str] = []
    if _SSN.search(text):
        found.append("ssn")
    if _EMAIL.search(text):
        found.append("email")
    if _PHONE.search(text):
        found.append("phone")
    if _LONG_ID.search(text):
        found.append("long_id")
    return found


def assert_deidentified(text: str) -> None:
    """Raise :class:`PHILeakError` if ``text`` still contains structured PHI."""
    leaks = residual_phi(text)
    if leaks:
        # Note: the offending text is NEVER included in the error (no PHI in logs).
        raise PHILeakError(f"refusing to send: residual PHI detected ({', '.join(leaks)})")
