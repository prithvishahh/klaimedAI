"""Triage scoring: recoverability and work-queue priority.

priority = denied_amount × p(win)

In Phase 0, p(win) is a per-class prior (``RECOVERABILITY``). Once the moat table
(``appeal_outcome``) has data, that prior is replaced by the measured win rate for
(payer × CARC × specialty × strategy) — the ranking gets sharper as we learn.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rcm.enums import RECOVERABILITY, TriageClass


def recoverability(triage_class: TriageClass) -> float:
    """Prior probability that a denial in this class is recoverable (0-1)."""
    return RECOVERABILITY[triage_class]


def priority(denied_amount: Decimal, p_win: float) -> Decimal:
    """Expected recoverable dollars: denied_amount × p(win), 2 dp."""
    result = denied_amount * Decimal(str(p_win))
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
