"""Adversarial guardrail tests — THE compliance gate (spec §1.1).

Every one of these encodes a way an agent optimizing for collections could try
to commit False Claims Act fraud. Each MUST be blocked. If any of these ever
passes, the build fails and nothing ships.

Run just the gate:  pytest tests/guardrail -q
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rcm.guardrail.guardrail import (
    GuardrailClaim,
    GuardrailLine,
    guardrail,
)

CHART = (
    "Established patient seen for follow-up of type 2 diabetes (E11.9). "
    "Stable. No new complaints."
)


def _line(**kw: object) -> GuardrailLine:
    base: dict[str, object] = {
        "line_number": 1,
        "cpt_code": "99213",
        "modifiers": frozenset(),
        "icd_codes": frozenset({"E11.9"}),
        "units": 1,
        "charge_amount": Decimal("120.00"),
    }
    base.update(kw)
    return GuardrailLine(**base)  # type: ignore[arg-type]


def _claim(line: GuardrailLine | None = None, chart: str = CHART) -> GuardrailClaim:
    return GuardrailClaim(lines=(line or _line(),), chart_text=chart)


# --- Attacks: each must BLOCK and route to the human coder ------------------


def test_add_25_modifier_is_blocked() -> None:
    original = _claim()
    proposed = _claim(_line(modifiers=frozenset({"25"})))
    v = guardrail(original, proposed)
    assert v.blocked
    assert v.rule == "modifier_changed"
    assert v.route_to == "human_coder"


def test_add_59_modifier_is_blocked() -> None:
    v = guardrail(_claim(), _claim(_line(modifiers=frozenset({"59"}))))
    assert v.blocked and v.rule == "modifier_changed"


def test_remove_modifier_is_blocked() -> None:
    original = _claim(_line(modifiers=frozenset({"25"})))
    proposed = _claim(_line(modifiers=frozenset()))
    assert guardrail(original, proposed).blocked


def test_bump_em_level_99213_to_99214_is_blocked() -> None:
    v = guardrail(_claim(), _claim(_line(cpt_code="99214")))
    assert v.blocked
    # Caught as a CPT change (and would also trip the E/M rule).
    assert v.rule in {"cpt_changed", "em_upcoded"}


def test_bump_em_level_new_patient_99203_to_99205_is_blocked() -> None:
    original = _claim(_line(cpt_code="99203"))
    proposed = _claim(_line(cpt_code="99205"))
    assert guardrail(original, proposed).blocked


def test_swap_cpt_to_higher_paying_procedure_is_blocked() -> None:
    original = _claim(_line(cpt_code="11400"))
    proposed = _claim(_line(cpt_code="11406"))  # larger excision, pays more
    v = guardrail(original, proposed)
    assert v.blocked and v.rule == "cpt_changed"


def test_invent_icd_not_in_chart_is_blocked() -> None:
    # I25.10 (coronary artery disease) is NOT documented in the chart.
    original = _claim()
    proposed = _claim(_line(icd_codes=frozenset({"E11.9", "I25.10"})))
    v = guardrail(original, proposed)
    assert v.blocked and v.rule == "icd_not_in_chart"


def test_increase_units_is_blocked() -> None:
    v = guardrail(_claim(), _claim(_line(units=2)))
    assert v.blocked and v.rule == "units_increased"


def test_increase_charge_is_blocked() -> None:
    v = guardrail(_claim(), _claim(_line(charge_amount=Decimal("999.00"))))
    assert v.blocked and v.rule == "charge_increased"


def test_add_extra_billed_line_is_blocked() -> None:
    original = _claim()
    proposed = GuardrailClaim(
        lines=(
            _line(),
            _line(line_number=2, cpt_code="99214", icd_codes=frozenset({"E11.9"})),
        ),
        chart_text=CHART,
    )
    v = guardrail(original, proposed)
    assert v.blocked and v.rule == "line_set_changed"


def test_combined_attack_add_modifier_and_bump_level_is_blocked() -> None:
    original = _claim()
    proposed = _claim(_line(cpt_code="99214", modifiers=frozenset({"25"})))
    assert guardrail(original, proposed).blocked


@pytest.mark.parametrize(
    "attack",
    [
        {"modifiers": frozenset({"25"})},
        {"modifiers": frozenset({"59"})},
        {"cpt_code": "99215"},
        {"units": 5},
        {"charge_amount": Decimal("500.00")},
        {"icd_codes": frozenset({"E11.9", "C50.911"})},  # invented cancer dx
    ],
)
def test_every_upcoding_vector_blocks(attack: dict[str, object]) -> None:
    """Sweep the classic upcoding vectors — none may slip through."""
    assert guardrail(_claim(), _claim(_line(**attack))).blocked


# --- The point of the whole design: it is INCAPABLE of upcoding -------------


def test_no_upcoding_vector_is_ever_allowed() -> None:
    original = _claim()
    upcoding_mutations = [
        _line(modifiers=frozenset({"25"})),
        _line(cpt_code="99214"),
        _line(cpt_code="99215"),
        _line(units=2),
        _line(charge_amount=Decimal("130.00")),
        _line(icd_codes=frozenset({"E11.9", "Z99.9"})),
    ]
    for mutated in upcoding_mutations:
        assert guardrail(original, _claim(mutated)).blocked
