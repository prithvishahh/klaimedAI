"""Outcome ingestion (spec 1.7) — closes the learning loop, feeds the moat.

When a returned 835 comes back for a claim we appealed, we match it to the pending
appeal, record the outcome (paid / partial / denied) and the dollars recovered, and
roll the result into ``appeal_outcome`` — the payer × CARC × specialty × strategy
win-rate table that nobody else can assemble (spec §4 learning loop).

This is pure database + arithmetic: no model calls, and **no PHI ever enters the
stats** — only reason codes, dollar amounts, and elapsed days. An appeal only
transitions out of ``pending`` here, and every transition is written to the
append-only audit log.

A win is any recovery (paid or partial). The aggregate columns are updated by exact
incremental means from the stored aggregates, so we never need to re-scan history:

    avg' = (avg × n + x) / (n + 1)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rcm.audit.log import record_action
from rcm.edi.segments import Remittance
from rcm.edi.x12_835 import remittance_to_denials
from rcm.enums import AppealOutcome
from rcm.models.entities import (
    Appeal,
    AppealOutcomeStat,
    Claim,
    Denial,
    Encounter,
    Provider,
)

_UNKNOWN_SPECIALTY = "unknown"
_CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    """The recorded result for one appeal (returned to the caller / demo)."""

    appeal_id: UUID
    claim_control_number: str
    carc_code: str
    outcome: str
    original_denied: Decimal
    recovered_amount: Decimal
    days_to_resolution: int | None


@dataclass(frozen=True, slots=True)
class MoatAggregate:
    """The rolled-up win-rate stats for one payer × CARC × specialty × strategy key.

    A plain value object so the arithmetic is testable and reusable without a
    database (the moat table stores exactly these fields)."""

    attempts: int
    wins: int
    win_rate: float
    avg_recovered: Decimal
    avg_days_to_resolution: float | None


def fold_outcome(
    prior: MoatAggregate | None,
    *,
    recovered: Decimal,
    won: bool,
    days: int | None,
) -> MoatAggregate:
    """Fold one resolved outcome into the running aggregate (exact incremental means).

    This is the single source of truth for the moat math: the DB rollup and the
    demo both call it, so what a viewer sees is the real computation.
    """
    n = prior.attempts if prior else 0
    new_n = n + 1
    new_wins = (prior.wins if prior else 0) + (1 if won else 0)

    prior_avg_rec = prior.avg_recovered if prior else Decimal("0")
    avg_rec = ((prior_avg_rec * n + recovered) / new_n).quantize(_CENTS)

    if days is None:
        avg_days = prior.avg_days_to_resolution if prior else None
    else:
        prior_days = (
            prior.avg_days_to_resolution
            if prior and prior.avg_days_to_resolution is not None
            else 0.0
        )
        avg_days = (prior_days * n + days) / new_n

    return MoatAggregate(new_n, new_wins, new_wins / new_n, avg_rec, avg_days)


def _classify(original: Decimal, recovered: Decimal) -> str:
    if original > 0 and recovered >= original:
        return AppealOutcome.PAID.value
    if recovered > 0:
        return AppealOutcome.PARTIAL.value
    return AppealOutcome.DENIED.value


def _specialty_for_claim(session: Session, claim: Claim) -> str:
    """Specialty behind the claim (via encounter → provider), or 'unknown'."""
    if claim.encounter_id is None:
        return _UNKNOWN_SPECIALTY
    specialty = session.execute(
        select(Provider.specialty)
        .join(Encounter, Encounter.provider_id == Provider.id)
        .where(Encounter.id == claim.encounter_id)
    ).scalar_one_or_none()
    return specialty or _UNKNOWN_SPECIALTY


def ingest_outcomes(
    session: Session,
    remittance: Remittance,
    *,
    actor: str = "outcome_ingestor",
    today: date | None = None,
) -> list[OutcomeResult]:
    """Match a returned remittance to pending appeals; record outcomes + moat stats.

    For every claim payment in the remittance we look up the claim by its control
    number, find any *submitted, still-pending* appeals on its denials, and compare
    the originally denied amount against what is still denied for that CARC in this
    remittance. The difference is the recovered amount, which decides the outcome.
    """
    today = today or date.today()

    # $ still denied per (claim control number, CARC) in the returned remittance.
    still_denied: dict[tuple[str, str], Decimal] = {}
    for row in remittance_to_denials(remittance):
        key = (row.patient_control_number, row.carc_code)
        still_denied[key] = still_denied.get(key, Decimal("0")) + row.denied_amount

    results: list[OutcomeResult] = []
    for clp in remittance.claims:
        ccn = clp.patient_control_number
        claim = session.execute(
            select(Claim).where(Claim.claim_control_number == ccn)
        ).scalar_one_or_none()
        if claim is None:
            continue

        appeals = (
            session.execute(
                select(Appeal)
                .join(Denial, Appeal.denial_id == Denial.id)
                .where(
                    Denial.claim_id == claim.id,
                    Appeal.outcome == AppealOutcome.PENDING.value,
                    Appeal.submitted_at.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        if not appeals:
            continue

        specialty = _specialty_for_claim(session, claim)
        for appeal in appeals:
            denial = session.get(Denial, appeal.denial_id)
            if denial is None:  # FK guarantees this cannot happen; keep it total
                continue
            original = denial.denied_amount
            still = still_denied.get((ccn, denial.carc_code), Decimal("0"))
            recovered = max(Decimal("0"), original - still)
            outcome = _classify(original, recovered)
            # Normalize to UTC before taking the calendar date: the DB returns the
            # timestamp in the session timezone, which would otherwise skew the day
            # count by one near midnight.
            days = (
                (today - appeal.submitted_at.astimezone(UTC).date()).days
                if appeal.submitted_at is not None
                else None
            )

            appeal.outcome = outcome
            appeal.recovered_amount = recovered
            appeal.outcome_date = today

            _roll_up_stat(
                session,
                payer_id=claim.payer_id,
                carc_code=denial.carc_code,
                specialty=specialty,
                strategy=appeal.strategy or "unknown",
                recovered=recovered,
                won=outcome != AppealOutcome.DENIED.value,
                days=days,
            )

            record_action(
                session,
                actor=actor,
                action="ingest_outcome",
                entity_type="appeal",
                entity_id=str(appeal.id),
                after={
                    "outcome": outcome,
                    "carc_code": denial.carc_code,
                    "original_denied": str(original),
                    "recovered_amount": str(recovered),
                    "days_to_resolution": days,
                },
            )
            results.append(
                OutcomeResult(
                    appeal_id=appeal.id,
                    claim_control_number=ccn,
                    carc_code=denial.carc_code,
                    outcome=outcome,
                    original_denied=original,
                    recovered_amount=recovered,
                    days_to_resolution=days,
                )
            )

    session.flush()
    return results


def _roll_up_stat(
    session: Session,
    *,
    payer_id: UUID,
    carc_code: str,
    specialty: str,
    strategy: str,
    recovered: Decimal,
    won: bool,
    days: int | None,
) -> AppealOutcomeStat:
    """Upsert the moat row for this (payer, CARC, specialty, strategy) key."""
    stat = session.execute(
        select(AppealOutcomeStat).where(
            AppealOutcomeStat.payer_id == payer_id,
            AppealOutcomeStat.carc_code == carc_code,
            AppealOutcomeStat.specialty == specialty,
            AppealOutcomeStat.strategy == strategy,
        )
    ).scalar_one_or_none()
    if stat is None:
        stat = AppealOutcomeStat(
            payer_id=payer_id,
            carc_code=carc_code,
            specialty=specialty,
            strategy=strategy,
            attempts=0,
            wins=0,
        )
        session.add(stat)

    prior = MoatAggregate(
        attempts=stat.attempts,
        wins=stat.wins,
        win_rate=stat.win_rate or 0.0,
        avg_recovered=stat.avg_recovered or Decimal("0"),
        avg_days_to_resolution=stat.avg_days_to_resolution,
    )
    agg = fold_outcome(prior, recovered=recovered, won=won, days=days)

    stat.attempts = agg.attempts
    stat.wins = agg.wins
    stat.win_rate = agg.win_rate
    stat.avg_recovered = agg.avg_recovered
    stat.avg_days_to_resolution = agg.avg_days_to_resolution
    session.flush()
    return stat
