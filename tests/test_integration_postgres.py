"""Postgres integration tests (require a live DB — run in CI / with docker).

Verifies the two database-level compliance controls end to end:
  * PHI is ciphertext at rest (the raw column never holds plaintext);
  * the audit log is append-only (UPDATE/DELETE are rejected).

Run:  docker compose up -d && alembic upgrade head && pytest -m postgres
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from rcm.audit.log import record_action
from rcm.core.config import get_settings
from rcm.models import Base
from rcm.models.entities import Denial, Patient

pytestmark = pytest.mark.postgres

# No '%' — psycopg would treat it as a parameter marker (see the migration).
_TRIGGER_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION rcm_prevent_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only; UPDATE/DELETE is not permitted';
    END;
    $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log",
    """
    CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION rcm_prevent_mutation();
    """,
)


@pytest.fixture(scope="module")
def engine():  # type: ignore[no-untyped-def]
    eng = create_engine(get_settings().database_url, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for stmt in _TRIGGER_STATEMENTS:
            conn.execute(text(stmt))
    yield eng
    Base.metadata.drop_all(eng)


def test_phi_is_ciphertext_at_rest(engine) -> None:  # type: ignore[no-untyped-def]
    from rcm.models.entities import Practice

    with Session(engine) as s:
        practice = Practice(name="T")
        s.add(practice)
        s.flush()
        p = Patient(practice_id=practice.id, name_enc="Jane Doe", dob_enc="1985-03-02")
        s.add(p)
        s.commit()
        pid = p.id

    # Raw column must NOT contain the plaintext.
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT name_enc FROM patient WHERE id = :id"), {"id": pid}
        ).scalar_one()
    assert raw != "Jane Doe"
    assert "Jane" not in raw

    # ORM read decrypts transparently.
    with Session(engine) as s:
        assert s.get(Patient, pid).name_enc == "Jane Doe"


def test_audit_log_rejects_update_and_delete(engine) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as s:
        entry = record_action(
            s, actor="test", action="unit", entity_type="denial", entity_id="x"
        )
        s.commit()
        eid = entry.id

    with engine.begin() as conn, pytest.raises(DatabaseError):
        conn.execute(text("UPDATE audit_log SET actor='tamper' WHERE id=:id"), {"id": eid})

    with engine.begin() as conn, pytest.raises(DatabaseError):
        conn.execute(text("DELETE FROM audit_log WHERE id=:id"), {"id": eid})


def test_denial_priority_and_deadline_persist(engine) -> None:  # type: ignore[no-untyped-def]
    from rcm.models.entities import Claim, Payer, Practice

    with Session(engine) as s:
        practice = Practice(name="T")
        payer = Payer(name="AETNA", payer_id_code="60054")
        s.add_all([practice, payer])
        s.flush()
        claim = Claim(
            practice_id=practice.id,
            payer_id=payer.id,
            claim_control_number="PCN1",
            total_charge=120,
        )
        s.add(claim)
        s.flush()
        s.add(
            Denial(
                claim_id=claim.id,
                carc_code="16",
                group_code="CO",
                denied_amount=120,
                denial_date=date(2026, 1, 15),
                appeal_deadline=date(2026, 7, 14),
                triage_class="administrative",
                recoverability_score=0.85,
                priority=102,
            )
        )
        s.commit()

    with Session(engine) as s:
        d = s.query(Denial).filter_by(carc_code="16").one()
        assert d.appeal_deadline == date(2026, 7, 14)
        assert float(d.priority) == 102.0


def test_write_path_records_guardrail_block_and_audit(engine) -> None:  # type: ignore[no-untyped-def]
    """A blocked outbound claim records a guardrail_block; an allowed one audits."""
    from dataclasses import replace

    from rcm.claims.corrections import CorrectionContext, propose_correction
    from rcm.claims.pipeline import GuardrailBlocked, prepare_outbound_837p
    from rcm.models.entities import AuditLog, GuardrailBlock
    from tests.claims.factories import RECEIVER, SUBMITTER, build_claim

    original = build_claim()

    # 1) Blocked: an upcoding attempt records a guardrail_block, emits no EDI.
    malicious = replace(
        original, lines=(replace(original.lines[0], modifiers=("25",)), *original.lines[1:])
    )
    with Session(engine) as s:
        with pytest.raises(GuardrailBlocked):
            prepare_outbound_837p(
                original, malicious, submitter=SUBMITTER, receiver=RECEIVER, session=s
            )
        s.commit()  # the guardrail_block row was flushed before the raise
        blocks = s.query(GuardrailBlock).filter_by(rule_violated="modifier_changed").count()
        assert blocks == 1

    # 2) Allowed: a data-only correction audits a generate_837p action.
    corrected = propose_correction(
        original, "140", CorrectionContext(verified_member_id="W999888777")
    ).corrected_claim
    with Session(engine) as s:
        prepare_outbound_837p(
            original, corrected, submitter=SUBMITTER, receiver=RECEIVER, session=s
        )
        s.commit()
        audits = s.query(AuditLog).filter_by(action="generate_837p").count()
        assert audits == 1


def test_pgvector_retriever_and_appeal_audit(engine) -> None:  # type: ignore[no-untyped-def]
    """RAG over pgvector retrieves the seeded policy; the appeal is audited."""
    from decimal import Decimal

    from rcm.appeals.agent import draft_appeal
    from rcm.appeals.model import AppealContext
    from rcm.appeals.retriever import PgVectorRetriever
    from rcm.models.entities import AuditLog, PolicyDoc
    from rcm.policy.embeddings import get_embedder
    from rcm.policy.scraper import scrape_policies
    from tests.claims.factories import build_claim

    seed = scrape_policies("dermatology")[0]
    with Session(engine) as s:
        s.add(
            PolicyDoc(
                doc_type=seed.doc_type,
                title=seed.title,
                text=seed.text,
                cpt_codes=list(seed.cpt_codes),
                url=seed.url,
                embedding=get_embedder().embed(seed.text),
            )
        )
        s.commit()

    with Session(engine) as s:
        retriever = PgVectorRetriever(s)
        hits = retriever.retrieve("skin lesion excision D48.5", cpt_codes=("11100",), k=1)
        assert hits and "Skin Lesions" in hits[0].title

        draft = draft_appeal(
            AppealContext(claim=build_claim(), carc_code="50", denied_amount=Decimal("150")),
            retriever=retriever,
            session=s,
        )
        s.commit()
        assert draft.appealable
        assert s.query(AuditLog).filter_by(action="draft_appeal").count() == 1
