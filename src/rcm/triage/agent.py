"""TRIAGE agent v0 (spec 0.5).

Classifies each denial into fixable / appealable / legitimate (or DANGER →
human coder), scores recoverability, and ranks the queue by ``$ × p(win)``.

Phase 0 triage is **mostly deterministic**: the CARC taxonomy is a fixed table,
so routing is a lookup. An optional model tie-break (Haiku) can disambiguate an
UNKNOWN CARC, but CARC codes are not PHI, and the deterministic path is the
default. The kill criterion (spec §10): ≥90% agreement with a human coder.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from rcm.enums import TriageClass
from rcm.taxonomy.carc import classify_carc
from rcm.triage.scoring import priority, recoverability


class Disposition(str, Enum):
    """What we do with a denial."""

    FIXABLE = "fixable"  # correct data + resubmit (highest ROI, lowest risk)
    APPEALABLE = "appealable"  # appeal with policy + chart evidence
    HUMAN_CODER = "human_coder"  # DANGER ZONE (bundling) — never automate
    CLOSE = "close"  # legitimate denial — don't waste the appeal
    REVIEW = "review"  # unmapped — human review


_DISPOSITION: dict[TriageClass, Disposition] = {
    TriageClass.ADMINISTRATIVE: Disposition.FIXABLE,
    TriageClass.ELIGIBILITY: Disposition.FIXABLE,
    TriageClass.AUTHORIZATION: Disposition.APPEALABLE,
    TriageClass.MEDICAL_NECESSITY: Disposition.APPEALABLE,
    TriageClass.BUNDLING: Disposition.HUMAN_CODER,
    TriageClass.LEGITIMATE: Disposition.CLOSE,
    TriageClass.UNKNOWN: Disposition.REVIEW,
}


@dataclass(frozen=True, slots=True)
class TriageResult:
    carc_code: str
    triage_class: TriageClass
    disposition: Disposition
    recoverability_score: float
    priority: Decimal


def triage(carc_code: str, denied_amount: Decimal) -> TriageResult:
    """Classify and score a single denial."""
    triage_class = classify_carc(carc_code)
    p_win = recoverability(triage_class)
    return TriageResult(
        carc_code=carc_code,
        triage_class=triage_class,
        disposition=_DISPOSITION[triage_class],
        recoverability_score=p_win,
        priority=priority(denied_amount, p_win),
    )


def rank(results: list[TriageResult]) -> list[TriageResult]:
    """Order a set of triaged denials by expected recoverable dollars, desc."""
    return sorted(results, key=lambda r: r.priority, reverse=True)
