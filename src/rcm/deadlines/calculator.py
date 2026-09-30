"""Timely-filing / appeal deadline calculator (spec 0.4).

A missed appeal deadline means the claim is dead forever — and *that* is our
liability, not the payer's (spec risk table). So the deadline is a first-class,
indexed object, and we alert at T-30 / T-14 / T-7.

Windows vary by payer. We keep a small per-payer table and a conservative
default. Filing window runs from date-of-service; appeal window runs from the
denial date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


@dataclass(frozen=True, slots=True)
class PayerWindows:
    filing_days: int  # from date of service to submit
    appeal_days: int  # from denial date to appeal


# Keyed by normalized payer name. Values are illustrative, conservative windows;
# a real deployment loads contracted windows per payer.
_PAYER_WINDOWS: dict[str, PayerWindows] = {
    "AETNA": PayerWindows(filing_days=120, appeal_days=180),
    "UNITEDHEALTHCARE": PayerWindows(filing_days=90, appeal_days=180),
    "CIGNA": PayerWindows(filing_days=90, appeal_days=180),
    "BCBS OF TEXAS": PayerWindows(filing_days=95, appeal_days=180),
    "MEDICARE": PayerWindows(filing_days=365, appeal_days=120),
}

# Conservative default when the payer is unknown: shortest common windows.
_DEFAULT = PayerWindows(filing_days=90, appeal_days=90)


def windows_for(payer_name: str) -> PayerWindows:
    return _PAYER_WINDOWS.get(payer_name.strip().upper(), _DEFAULT)


def filing_deadline(dos: date, payer_name: str) -> date:
    return dos + timedelta(days=windows_for(payer_name).filing_days)


def appeal_deadline(denial_date: date, payer_name: str) -> date:
    """The date by which an appeal MUST be submitted. Indexed on the denial row."""
    return denial_date + timedelta(days=windows_for(payer_name).appeal_days)


def days_until(deadline: date, today: date | None = None) -> int:
    """Whole days from ``today`` until ``deadline`` (negative if already past)."""
    return (deadline - (today or date.today())).days


class DeadlineRisk(str, Enum):
    PAST_DUE = "past_due"
    T_MINUS_7 = "t_minus_7"
    T_MINUS_14 = "t_minus_14"
    T_MINUS_30 = "t_minus_30"
    OK = "ok"


def deadline_risk(deadline: date, today: date | None = None) -> DeadlineRisk:
    """Bucket a deadline for alerting (T-30 / T-14 / T-7 / past due)."""
    remaining = days_until(deadline, today)
    if remaining < 0:
        return DeadlineRisk.PAST_DUE
    if remaining <= 7:
        return DeadlineRisk.T_MINUS_7
    if remaining <= 14:
        return DeadlineRisk.T_MINUS_14
    if remaining <= 30:
        return DeadlineRisk.T_MINUS_30
    return DeadlineRisk.OK
