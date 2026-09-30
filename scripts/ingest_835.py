#!/usr/bin/env python3
"""Ingest synthetic 835s into Postgres: parse → triage → deadlines → denial rows.

Ties the Phase 0 read-only pipeline together (spec 0.1/0.4/0.5/0.7). Requires a
running database (docker compose up + alembic upgrade head).

  parse 835  →  DenialRow
             →  TRIAGE (class, recoverability, priority = $ × p(win))
             →  appeal_deadline (per-payer window, INDEXED)
             →  write Payer/Claim/Denial + an append-only audit record

Usage:  python scripts/ingest_835.py data/samples/*.sample.835
"""

from __future__ import annotations

import glob
import sys
from datetime import date

from sqlalchemy import select

from rcm.audit.log import record_action
from rcm.core.db import session_scope
from rcm.deadlines.calculator import appeal_deadline
from rcm.edi.x12_835 import parse_file
from rcm.models.entities import Claim, Denial, Payer, Practice
from rcm.triage.agent import triage


def _get_or_create_practice(session) -> Practice:  # type: ignore[no-untyped-def]
    practice = session.scalars(select(Practice).limit(1)).first()
    if practice is None:
        practice = Practice(name="BEACHHEAD DERMATOLOGY", ehr_system="synthetic")
        session.add(practice)
        session.flush()
    return practice


def _get_or_create_payer(session, name: str) -> Payer:  # type: ignore[no-untyped-def]
    payer = session.scalars(select(Payer).where(Payer.name == name)).first()
    if payer is None:
        payer = Payer(name=name, payer_id_code=name[:8].upper())
        session.add(payer)
        session.flush()
    return payer


def ingest(paths: list[str]) -> int:
    denial_count = 0
    today = date.today()
    with session_scope() as session:
        practice = _get_or_create_practice(session)
        for path in sorted(paths):
            for row in parse_file(path):
                payer = _get_or_create_payer(session, row.payer_name or "UNKNOWN")
                claim = Claim(
                    practice_id=practice.id,
                    payer_id=payer.id,
                    claim_control_number=row.patient_control_number,
                    total_charge=row.denied_amount,
                    status="denied",
                )
                session.add(claim)
                session.flush()

                result = triage(row.carc_code, row.denied_amount)
                denial = Denial(
                    claim_id=claim.id,
                    carc_code=row.carc_code,
                    group_code=row.group_code,
                    denied_amount=row.denied_amount,
                    denial_date=today,
                    appeal_deadline=appeal_deadline(today, row.payer_name or "UNKNOWN"),
                    triage_class=result.triage_class.value,
                    recoverability_score=result.recoverability_score,
                    priority=result.priority,
                )
                session.add(denial)
                session.flush()
                record_action(
                    session,
                    actor="ingest_835",
                    action="triage_denial",
                    entity_type="denial",
                    entity_id=str(denial.id),
                    after={
                        "carc_code": row.carc_code,
                        "triage_class": result.triage_class.value,
                        "priority": str(result.priority),
                    },
                )
                denial_count += 1
    return denial_count


def main() -> int:
    paths: list[str] = []
    for arg in sys.argv[1:]:
        paths.extend(glob.glob(arg))
    if not paths:
        print("usage: python scripts/ingest_835.py <835 file(s) or glob>", file=sys.stderr)
        return 2
    n = ingest(paths)
    print(f"ingested {n} denial rows from {len(paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
