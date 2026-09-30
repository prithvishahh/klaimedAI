"""Append-only audit log writer (spec 0.7).

Every agent action, its model, a hash of the prompt (never the prompt body), and
the before/after state (encrypted at rest) are appended here. The table is
append-only: a Postgres trigger rejects UPDATE/DELETE and the app role lacks
those grants (see alembic). This module only ever INSERTs.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rcm.llm.client import prompt_hash
from rcm.models.entities import AuditLog, GuardrailBlock


def record_action(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    model: str | None = None,
    prompt: str | None = None,
    prompt_hash_value: str | None = None,
) -> AuditLog:
    """Append one audit record. Returns the (flushed) row.

    ``before``/``after`` are serialized to JSON and encrypted by the column type.
    ``prompt`` is hashed — its body is never stored or logged. When only the hash
    is available (the drafter already hashed the prompt), pass ``prompt_hash_value``.
    """
    ph = prompt_hash(prompt) if prompt is not None else prompt_hash_value
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=json.dumps(before, sort_keys=True) if before is not None else None,
        after_json=json.dumps(after, sort_keys=True) if after is not None else None,
        model=model,
        prompt_hash=ph,
    )
    session.add(entry)
    session.flush()
    return entry


def record_guardrail_block(
    session: Session,
    *,
    agent: str,
    rule_violated: str,
    attempted_change: dict[str, Any] | None = None,
    claim_id: UUID | None = None,
) -> GuardrailBlock:
    """Record a guardrail BLOCK and the change it refused (routed to a coder)."""
    block = GuardrailBlock(
        claim_id=claim_id,
        agent=agent,
        attempted_change_json=attempted_change,
        rule_violated=rule_violated,
    )
    session.add(block)
    session.flush()
    return block
