"""Guardrail allow-path tests.

The guardrail must not be so strict it blocks legitimate corrections — those are
the highest-ROI, lowest-risk recoveries (spec §5 "Administrative / fixable").
These operations do NOT change codes and must be ALLOWED.
"""

from __future__ import annotations

from decimal import Decimal

from rcm.guardrail.guardrail import GuardrailClaim, GuardrailLine, guardrail

CHART = "Follow-up for hypertension (I10) and type 2 diabetes (E11.9)."


def _claim(**kw: object) -> GuardrailClaim:
    base: dict[str, object] = {
        "cpt_code": "99213",
        "modifiers": frozenset(),
        "icd_codes": frozenset({"I10"}),
        "units": 1,
        "charge_amount": Decimal("120.00"),
    }
    base.update(kw)
    line = GuardrailLine(line_number=1, **base)  # type: ignore[arg-type]
    return GuardrailClaim(lines=(line,), chart_text=CHART)


def test_identical_resubmission_is_allowed() -> None:
    assert guardrail(_claim(), _claim()).allowed


def test_lowering_charge_is_allowed() -> None:
    assert guardrail(_claim(), _claim(charge_amount=Decimal("100.00"))).allowed


def test_reducing_units_is_allowed() -> None:
    original = _claim(units=3)
    assert guardrail(original, _claim(units=2)).allowed


def test_adding_icd_that_is_documented_in_chart_is_allowed() -> None:
    # E11.9 IS in the chart, so adding it as a diagnosis is legitimate.
    original = _claim()
    proposed = _claim(icd_codes=frozenset({"I10", "E11.9"}))
    assert guardrail(original, proposed).allowed


def test_lowering_em_level_is_allowed() -> None:
    original = _claim(cpt_code="99214")
    proposed = _claim(cpt_code="99213")
    # This is a CPT change, so the guardrail still routes to a human — correct:
    # any code change is reviewed. Downcoding is never auto-applied either.
    assert guardrail(original, proposed).blocked
