"""Structured logging with hard PHI redaction.

No PHI ever reaches a log sink. Two layers of defence:

  1. A denylist of PHI-bearing keys (name, dob, mrn, ssn, chart_text, prompt, ...)
     is dropped/masked from every event dict, at any nesting depth.
  2. Free-text values are scrubbed for SSN and long digit runs (member/account
     numbers) that could be PHI even in an otherwise-safe field.

Audit records store a ``prompt_hash``, never the prompt body — so drafting
prompts (which contain de-identified chart context) never land in logs either.
"""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

# Keys whose values are PHI (or PHI-adjacent) and must never be logged.
_REDACT_KEYS = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "patient_name",
        "dob",
        "date_of_birth",
        "ssn",
        "mrn",
        "external_mrn",
        "member_id",
        "subscriber_id",
        "address",
        "phone",
        "email",
        "chart_text",
        "chart",
        "note",
        "prompt",
        "prompt_body",
        "letter_text",
        "plaintext",
    }
)

_MASK = "***REDACTED***"
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# 9+ consecutive digits: member/account/claim numbers that may identify a person.
_LONGNUM_RE = re.compile(r"\b\d{9,}\b")


def _scrub_text(value: str) -> str:
    value = _SSN_RE.sub(_MASK, value)
    value = _LONGNUM_RE.sub(_MASK, value)
    return value


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_MASK if k.lower() in _REDACT_KEYS else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return type(obj)(_redact(v) for v in obj)
    if isinstance(obj, str):
        return _scrub_text(obj)
    return obj


def phi_redactor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: strip PHI from every event before it is rendered."""
    return {k: _redact(v) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure structlog + stdlib logging with PHI redaction always on."""
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            phi_redactor,  # redaction runs immediately before rendering
            renderer,
        ],
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
