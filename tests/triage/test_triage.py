"""TRIAGE v0 tests, including the ≥90% coder-agreement kill criterion (spec §10)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from rcm.enums import TriageClass
from rcm.triage.agent import Disposition, rank, triage

GOLDEN = Path(__file__).with_name("golden_denials.json")


def test_administrative_is_fixable_and_high_priority() -> None:
    r = triage("16", Decimal("120.00"))
    assert r.triage_class is TriageClass.ADMINISTRATIVE
    assert r.disposition is Disposition.FIXABLE
    assert r.priority == Decimal("102.00")  # 120 * 0.85


def test_bundling_always_routes_to_human_coder() -> None:
    r = triage("97", Decimal("500.00"))
    assert r.triage_class is TriageClass.BUNDLING
    assert r.disposition is Disposition.HUMAN_CODER
    # Danger zone: automated recoverability is 0 so it never tops the queue.
    assert r.priority == Decimal("0.00")


def test_legitimate_denial_is_closed() -> None:
    assert triage("204", Decimal("120.00")).disposition is Disposition.CLOSE


def test_medical_necessity_is_appealable() -> None:
    assert triage("50", Decimal("180.00")).disposition is Disposition.APPEALABLE


def test_unknown_carc_routes_to_review_never_auto_recovered() -> None:
    r = triage("99999", Decimal("100.00"))
    assert r.triage_class is TriageClass.UNKNOWN
    assert r.disposition is Disposition.REVIEW


def test_ranking_orders_by_expected_dollars() -> None:
    results = [
        triage("50", Decimal("1000.00")),  # 0.40 -> 400
        triage("16", Decimal("120.00")),   # 0.85 -> 102
        triage("204", Decimal("999.00")),  # 0.0  -> 0
    ]
    ordered = rank(results)
    assert [r.carc_code for r in ordered] == ["50", "16", "204"]


def test_agreement_with_human_coder_at_least_90pct() -> None:
    """The whole thesis: TRIAGE must agree with a coder ≥90% (spec §10)."""
    data = json.loads(GOLDEN.read_text())["denials"]
    agree = 0
    for row in data:
        predicted = triage(row["carc"], Decimal(row["amount"])).triage_class
        if predicted.value == row["human_class"]:
            agree += 1
    agreement = agree / len(data)
    assert agreement >= 0.90, f"triage agreement {agreement:.1%} < 90% kill criterion"
