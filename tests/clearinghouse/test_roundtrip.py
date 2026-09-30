"""Clearinghouse round-trip (spec 1.4): submit 837P -> 277CA ack -> 835 remit."""

from __future__ import annotations

from rcm.claims.corrections import CorrectionContext
from rcm.claims.pipeline import correct_and_prepare, submit_outbound
from rcm.clearinghouse.simulated import SimulatedClearinghouse
from rcm.clearinghouse.x12_277 import parse_277ca
from rcm.edi.x12_835 import parse_835, remittance_to_denials
from tests.claims.factories import RECEIVER, SUBMITTER, build_claim


def _corrected_outbound():  # type: ignore[no-untyped-def]
    _result, outbound = correct_and_prepare(
        build_claim(),
        "140",
        CorrectionContext(verified_member_id="W999888777"),  # differs from factory
        submitter=SUBMITTER,
        receiver=RECEIVER,
    )
    assert outbound is not None
    return outbound


def test_full_loop_corrected_claim_is_accepted_then_paid() -> None:
    ch = SimulatedClearinghouse(pay=True)
    outbound = _corrected_outbound()

    # Submit -> 277CA accepted (front-end acceptance).
    receipt = submit_outbound(outbound, ch)
    assert receipt.accepted
    acks = parse_277ca(receipt.ack_277ca)
    assert acks[0].accepted

    # 835 remittance comes back PAID -> zero denial rows (the loop closed).
    remit = ch.remittance(receipt.control_number)
    assert remit is not None
    denials = remittance_to_denials(parse_835(remit))
    assert denials == []


def test_invalid_837p_is_front_end_rejected_not_denied() -> None:
    ch = SimulatedClearinghouse()
    outbound = _corrected_outbound()
    # Tamper the total so CLM != sum of lines -> front-end (277CA) rejection.
    broken = outbound.edi_837p.replace("CLM*PCN00001*270.00", "CLM*PCN00001*999.00")

    receipt = ch.submit(broken)
    assert not receipt.accepted
    assert receipt.errors  # never reached adjudication — distinct from a denial
    acks = parse_277ca(receipt.ack_277ca)
    assert acks[0].category == "A3"
    # No remittance for a rejected claim.
    assert ch.remittance(receipt.control_number) is None


def test_no_pay_clearinghouse_returns_pending() -> None:
    ch = SimulatedClearinghouse(pay=False)
    receipt = submit_outbound(_corrected_outbound(), ch)
    assert receipt.accepted
    assert ch.remittance(receipt.control_number) is None  # accepted but not yet paid
