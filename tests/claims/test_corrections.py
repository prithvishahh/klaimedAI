"""Corrections agent tests (spec 1.2) — data-only, easy class, lines untouched."""

from __future__ import annotations

from datetime import date

from rcm.claims.corrections import CorrectionContext, propose_correction
from rcm.claims.model import Payer
from tests.claims.factories import build_claim


def test_co140_member_id_fix_is_correctable_and_changes_only_data() -> None:
    original = build_claim()
    ctx = CorrectionContext(verified_member_id="W999888777")
    result = propose_correction(original, "140", ctx)

    assert result.correctable
    assert result.corrected_claim is not None
    # The ONLY change is the member ID; every service line is byte-identical.
    assert result.corrected_claim.subscriber.member_id == "W999888777"
    assert result.corrected_claim.lines == original.lines
    assert [c.field for c in result.changes] == ["subscriber.member_id"]


def test_co16_demographic_fix() -> None:
    original = build_claim()
    ctx = CorrectionContext(corrected_dob=date(1985, 3, 20))
    result = propose_correction(original, "16", ctx)
    assert result.correctable
    assert result.corrected_claim.subscriber.dob == date(1985, 3, 20)
    assert result.corrected_claim.lines == original.lines


def test_eligibility_rebill_to_corrected_payer() -> None:
    original = build_claim()
    new_payer = Payer(name="UNITEDHEALTHCARE", payer_id="87726")
    result = propose_correction(original, "27", CorrectionContext(corrected_payer=new_payer))
    assert result.correctable
    assert result.strategy == "eligibility_rebill"
    assert result.corrected_claim.payer.payer_id == "87726"
    assert result.corrected_claim.lines == original.lines


def test_bundling_denial_is_refused_and_routed_to_human() -> None:
    result = propose_correction(
        build_claim(), "97", CorrectionContext(verified_member_id="X")
    )
    assert not result.correctable
    assert result.route_to == "human_coder"
    assert result.corrected_claim is None


def test_medical_necessity_denial_is_routed_to_appeal() -> None:
    result = propose_correction(build_claim(), "50", CorrectionContext())
    assert not result.correctable
    assert result.route_to == "appeal"


def test_no_verified_data_is_not_correctable() -> None:
    # Easy-class CARC but nothing to correct with -> route to human, don't invent.
    result = propose_correction(build_claim(), "140", CorrectionContext())
    assert not result.correctable
    assert result.route_to == "human_coder"


def test_agent_never_touches_codes_across_all_strategies() -> None:
    original = build_claim()
    for carc, ctx in [
        ("140", CorrectionContext(verified_member_id="M2")),
        ("16", CorrectionContext(corrected_last_name="SMITH")),
        ("27", CorrectionContext(corrected_payer=Payer("CIGNA", "62308"))),
    ]:
        r = propose_correction(original, carc, ctx)
        assert r.correctable and r.corrected_claim is not None
        # Invariant: code-bearing fields are identical to the original.
        assert r.corrected_claim.lines == original.lines
