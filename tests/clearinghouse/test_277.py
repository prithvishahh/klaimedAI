"""277CA build/parse tests (spec 1.4)."""

from __future__ import annotations

from rcm.clearinghouse.x12_277 import ClaimAck, build_277ca, parse_277ca


def test_accept_roundtrip() -> None:
    acks = [ClaimAck.accept("PCN00001")]
    parsed = parse_277ca(build_277ca(acks))
    assert len(parsed) == 1
    assert parsed[0].control_number == "PCN00001"
    assert parsed[0].accepted
    assert parsed[0].category == "A2"


def test_reject_roundtrip_carries_message() -> None:
    acks = [ClaimAck.reject("PCN00002", "missing subscriber member id")]
    parsed = parse_277ca(build_277ca(acks))
    assert not parsed[0].accepted
    assert parsed[0].category == "A3"
    assert "member id" in parsed[0].message


def test_mixed_batch() -> None:
    parsed = parse_277ca(
        build_277ca([ClaimAck.accept("A"), ClaimAck.reject("B", "bad format")])
    )
    by_id = {a.control_number: a for a in parsed}
    assert by_id["A"].accepted
    assert not by_id["B"].accepted
