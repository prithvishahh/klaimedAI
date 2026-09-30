"""Read-only API routes for Phase 0.

By design there is **no write path** here — no endpoint mutates a claim, submits
an appeal, or sends anything outbound. Phase 0 is read-only; the absence of write
routes is a security property, not an omission.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from rcm.core.config import get_settings
from rcm.core.db import session_scope
from rcm.deadlines.calculator import deadline_risk
from rcm.models.entities import Denial

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness + which environment we're in. No DB required."""
    return {"status": "ok", "env": get_settings().env}


@router.get("/denials/queue")
def denial_queue(limit: int = Query(25, ge=1, le=200)) -> list[dict[str, Any]]:
    """Top denials by expected recoverable dollars (priority = $ × p(win))."""
    with session_scope() as session:
        rows = session.scalars(
            select(Denial).order_by(Denial.priority.desc().nullslast()).limit(limit)
        ).all()
        return [
            {
                "id": str(d.id),
                "carc_code": d.carc_code,
                "group_code": d.group_code,
                "triage_class": d.triage_class,
                "denied_amount": float(d.denied_amount),
                "recoverability_score": d.recoverability_score,
                "priority": float(d.priority) if d.priority is not None else None,
                "appeal_deadline": d.appeal_deadline.isoformat()
                if d.appeal_deadline
                else None,
            }
            for d in rows
        ]


@router.get("/deadlines/at-risk")
def deadlines_at_risk(within_days: int = Query(30, ge=1, le=180)) -> list[dict[str, Any]]:
    """Denials whose appeal deadline is within ``within_days`` (T-30/14/7 alerts)."""
    cutoff = date.today() + timedelta(days=within_days)
    with session_scope() as session:
        rows = session.scalars(
            select(Denial)
            .where(Denial.appeal_deadline.is_not(None))
            .where(Denial.appeal_deadline <= cutoff)
            .order_by(Denial.appeal_deadline.asc())
        ).all()
        return [
            {
                "id": str(d.id),
                "carc_code": d.carc_code,
                "appeal_deadline": d.appeal_deadline.isoformat()
                if d.appeal_deadline
                else None,
                "risk": deadline_risk(d.appeal_deadline).value
                if d.appeal_deadline
                else None,
                "denied_amount": float(d.denied_amount),
            }
            for d in rows
        ]
