"""Write-path guardrail gate tests (spec 1.1 on the outbound path).

The corrections agent is data-only, but the pipeline does not trust that — it
diffs every outbound claim against the original. These tests prove the write
path is architecturally incapable of emitting an upcoded 837P: any code change
is BLOCKED and NO EDI is produced.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from rcm.claims.corrections import CorrectionContext
from rcm.claims.pipeline import (
    GuardrailBlocked,
    correct_and_prepare,
    prepare_outbound_837p,
)
from rcm.claims.x12_837 import validate_837p
from tests.claims.factories import RECEIVER, SUBMITTER, build_claim


def _mutate_line0(claim, **changes):  # type: ignore[no-untyped-def]
    new_line0 = replace(claim.lines[0], **changes)
    return replace(claim, lines=(new_line0, *claim.lines[1:]))


# --- The legitimate path clears the gate and produces valid EDI -------------


def test_legitimate_correction_passes_and_emits_valid_837p() -> None:
    original = build_claim()
    result, outbound = correct_and_prepare(
        original,
        "140",
        CorrectionContext(verified_member_id="W999888777"),
        submitter=SUBMITTER,
        receiver=RECEIVER,
    )
    assert result.correctable
    assert outbound is not None
    assert outbound.verdict.allowed
    assert validate_837p(outbound.edi_837p) == []
    assert "W999888777" in outbound.edi_837p


# --- Every upcoding attempt is BLOCKED, no EDI produced ----------------------


def test_added_modifier_is_blocked_no_edi() -> None:
    original = build_claim()
    malicious = _mutate_line0(original, modifiers=("25",))
    with pytest.raises(GuardrailBlocked) as exc:
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)
    assert exc.value.verdict.rule == "modifier_changed"
    assert exc.value.verdict.route_to == "human_coder"


def test_cpt_upcode_is_blocked_no_edi() -> None:
    original = build_claim()
    malicious = _mutate_line0(original, cpt_code="99215")
    with pytest.raises(GuardrailBlocked) as exc:
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)
    assert exc.value.verdict.rule in {"cpt_changed", "em_upcoded"}


def test_units_increase_is_blocked_no_edi() -> None:
    original = build_claim()
    malicious = _mutate_line0(original, units=3)
    with pytest.raises(GuardrailBlocked):
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)


def test_charge_increase_is_blocked_no_edi() -> None:
    original = build_claim()
    malicious = _mutate_line0(original, charge_amount=Decimal("999.00"))
    with pytest.raises(GuardrailBlocked):
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)


def test_invented_diagnosis_is_blocked_no_edi() -> None:
    original = build_claim()
    # C50.911 (breast cancer) is not in the chart -> invented -> blocked.
    malicious = _mutate_line0(original, diagnosis_codes=("E11.9", "C50.911"))
    with pytest.raises(GuardrailBlocked) as exc:
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)
    assert exc.value.verdict.rule == "icd_not_in_chart"


def test_out_of_class_denial_produces_no_outbound() -> None:
    result, outbound = correct_and_prepare(
        build_claim(),
        "97",  # bundling — danger zone
        CorrectionContext(verified_member_id="X"),
        submitter=SUBMITTER,
        receiver=RECEIVER,
    )
    assert not result.correctable
    assert outbound is None
    assert result.route_to == "human_coder"
