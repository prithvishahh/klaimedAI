"""Deadline calculator tests (spec 0.4)."""

from __future__ import annotations

from datetime import date

from rcm.deadlines.calculator import (
    DeadlineRisk,
    appeal_deadline,
    days_until,
    deadline_risk,
    filing_deadline,
)


def test_appeal_deadline_uses_payer_window() -> None:
    denial = date(2026, 1, 15)
    assert appeal_deadline(denial, "AETNA") == date(2026, 7, 14)  # +180d


def test_unknown_payer_uses_conservative_default() -> None:
    denial = date(2026, 1, 15)
    # Default appeal window is the shortest (90d) — fail safe, not generous.
    assert appeal_deadline(denial, "SOME UNKNOWN PAYER") == date(2026, 4, 15)


def test_filing_deadline_from_dos() -> None:
    assert filing_deadline(date(2026, 1, 1), "MEDICARE") == date(2027, 1, 1)  # +365d


def test_days_until_and_risk_buckets() -> None:
    today = date(2026, 1, 1)
    assert days_until(date(2026, 1, 6), today) == 5
    assert deadline_risk(date(2026, 1, 6), today) is DeadlineRisk.T_MINUS_7
    assert deadline_risk(date(2026, 1, 12), today) is DeadlineRisk.T_MINUS_14
    assert deadline_risk(date(2026, 1, 25), today) is DeadlineRisk.T_MINUS_30
    assert deadline_risk(date(2026, 3, 1), today) is DeadlineRisk.OK
    assert deadline_risk(date(2025, 12, 30), today) is DeadlineRisk.PAST_DUE
