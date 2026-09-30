"""Outcome ingestion + moat rollup (spec 1.7) — requires a live Postgres.

Verifies the learning loop end to end: a returned 835 flips a pending appeal to a
recorded outcome, writes the dollars recovered, rolls the result into the
``appeal_outcome`` win-rate table with correct incremental means, audits every
transition, and is idempotent (a re-ingest does not double-count).

Run:  scripts/dev_db.sh start && scripts/dev_db.sh migrate && pytest -m postgres
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from rcm.appeals.outcomes import ingest_outcomes
from rcm.core.config import get_settings
from rcm.edi.segments import Adjustment, ClaimPayment, Remittance
from rcm.models import Base
from rcm.models.entities import (
    Appeal,
    AppealOutcomeStat,
    AuditLog,
    Claim,
    Denial,
    Encounter,
    Patient,
    Payer,
    Practice,
    Provider,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():  # type: ignore[no-untyped-def]
    eng = create_engine(get_settings().database_url, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture(autouse=True)
def _clean(engine):  # type: ignore[no-untyped-def]
    """Each test starts from an empty set of the tables it touches."""
    yield
    with Session(engine) as s:
        s.execute(text(
            "TRUNCATE audit_log, appeal_outcome, appeal, denial, claim, encounter, "
            "patient, provider, payer, practice RESTART IDENTITY CASCADE"
        ))
        s.commit()


def _seed_appeal(
    s: Session,
    *,
    ccn: str,
    denied: Decimal,
    submitted: datetime,
    specialty: str = "dermatology",
    carc: str = "50",
    payer: Payer | None = None,
) -> tuple[Payer, Appeal]:
    """Create the practice→...→appeal chain for one submitted, pending appeal."""
    practice = Practice(name="Derm Group")
    payer = payer or Payer(name="AETNA", payer_id_code="60054")
    s.add_all([practice, payer])
    s.flush()
    provider = Provider(practice_id=practice.id, npi="1999999992", name="Dr D", specialty=specialty)
    patient = Patient(practice_id=practice.id)
    s.add_all([provider, patient])
    s.flush()
    enc = Encounter(practice_id=practice.id, patient_id=patient.id,
                    provider_id=provider.id, dos=date(2025, 12, 1))
    s.add(enc)
    s.flush()
    claim = Claim(practice_id=practice.id, encounter_id=enc.id, payer_id=payer.id,
                  claim_control_number=ccn, total_charge=denied)
    s.add(claim)
    s.flush()
    denial = Denial(claim_id=claim.id, carc_code=carc, group_code="CO", denied_amount=denied)
    s.add(denial)
    s.flush()
    appeal = Appeal(denial_id=denial.id, strategy="medical_necessity",
                    outcome="pending", submitted_at=submitted)
    s.add(appeal)
    s.flush()
    return payer, appeal


def _paid(ccn: str, charge: Decimal) -> ClaimPayment:
    """A claim payment with no remaining adjustments — fully recovered."""
    return ClaimPayment(patient_control_number=ccn, claim_status="1",
                        total_charge=charge, total_paid=charge,
                        patient_responsibility=Decimal("0"), payer_claim_control_number="P")


def _still_denied(ccn: str, charge: Decimal, carc: str, amount: Decimal) -> ClaimPayment:
    """A claim payment that still carries a CO-<carc> adjustment for ``amount``."""
    cas = Adjustment(group_code="CO", carc_code=carc, amount=amount)
    return ClaimPayment(patient_control_number=ccn, claim_status="4",
                        total_charge=charge, total_paid=charge - amount,
                        patient_responsibility=Decimal("0"), payer_claim_control_number="P",
                        claim_adjustments=[cas])


def test_won_appeal_records_outcome_and_moat(engine) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as s:
        payer, appeal = _seed_appeal(
            s, ccn="PCN-WIN", denied=Decimal("150"),
            submitted=datetime(2026, 1, 1, tzinfo=UTC),
        )
        s.commit()
        appeal_id, payer_id = appeal.id, payer.id

    remit = Remittance(payer_name="AETNA", claims=[_paid("PCN-WIN", Decimal("150"))])
    with Session(engine) as s:
        results = ingest_outcomes(s, remit, today=date(2026, 1, 21))
        s.commit()

    assert len(results) == 1
    r = results[0]
    assert r.outcome == "paid"
    assert r.recovered_amount == Decimal("150")
    assert r.days_to_resolution == 20

    with Session(engine) as s:
        appeal = s.get(Appeal, appeal_id)
        assert appeal.outcome == "paid"
        assert appeal.recovered_amount == Decimal("150.00")
        assert appeal.outcome_date == date(2026, 1, 21)

        stat = s.execute(select(AppealOutcomeStat).where(
            AppealOutcomeStat.payer_id == payer_id, AppealOutcomeStat.carc_code == "50")
        ).scalar_one()
        assert stat.attempts == 1 and stat.wins == 1
        assert stat.win_rate == pytest.approx(1.0)
        assert stat.avg_recovered == Decimal("150.00")
        assert stat.avg_days_to_resolution == pytest.approx(20.0)
        assert stat.specialty == "dermatology" and stat.strategy == "medical_necessity"

        # every transition is audited
        assert s.query(AuditLog).filter_by(action="ingest_outcome").count() == 1


def test_moat_aggregates_loss_and_partial(engine) -> None:  # type: ignore[no-untyped-def]
    """A loss and a partial on the same key average correctly (win_rate 0.5)."""
    with Session(engine) as s:
        payer = Payer(name="AETNA", payer_id_code="60054")
        s.add(payer)
        s.flush()
        _seed_appeal(s, ccn="PCN-LOSS", denied=Decimal("100"),
                     submitted=datetime(2026, 1, 1, tzinfo=UTC), payer=payer)
        _seed_appeal(s, ccn="PCN-PART", denied=Decimal("200"),
                     submitted=datetime(2026, 1, 1, tzinfo=UTC), payer=payer)
        s.commit()
        payer_id = payer.id

    remit = Remittance(payer_name="AETNA", claims=[
        _still_denied("PCN-LOSS", Decimal("100"), "50", Decimal("100")),  # recovered 0 -> loss
        _still_denied("PCN-PART", Decimal("200"), "50", Decimal("100")),  # recovered 100 -> partial
    ])
    with Session(engine) as s:
        results = ingest_outcomes(s, remit, today=date(2026, 1, 11))  # 10 days each
        s.commit()

    outcomes = {r.claim_control_number: r for r in results}
    assert outcomes["PCN-LOSS"].outcome == "denied"
    assert outcomes["PCN-PART"].outcome == "partial"
    assert outcomes["PCN-PART"].recovered_amount == Decimal("100")

    with Session(engine) as s:
        stat = s.execute(select(AppealOutcomeStat).where(
            AppealOutcomeStat.payer_id == payer_id)).scalar_one()
        assert stat.attempts == 2 and stat.wins == 1
        assert stat.win_rate == pytest.approx(0.5)
        assert stat.avg_recovered == Decimal("50.00")          # (0 + 100) / 2
        assert stat.avg_days_to_resolution == pytest.approx(10.0)


def test_reingest_is_idempotent(engine) -> None:  # type: ignore[no-untyped-def]
    """A resolved appeal is no longer pending, so a re-ingest does not double-count."""
    with Session(engine) as s:
        _seed_appeal(s, ccn="PCN-IDEM", denied=Decimal("80"),
                     submitted=datetime(2026, 1, 1, tzinfo=UTC))
        s.commit()

    remit = Remittance(payer_name="AETNA", claims=[_paid("PCN-IDEM", Decimal("80"))])
    with Session(engine) as s:
        assert len(ingest_outcomes(s, remit, today=date(2026, 1, 10))) == 1
        s.commit()
    with Session(engine) as s:
        assert ingest_outcomes(s, remit, today=date(2026, 1, 10)) == []  # nothing pending
        s.commit()
        stat = s.execute(select(AppealOutcomeStat)).scalar_one()
        assert stat.attempts == 1  # not 2
