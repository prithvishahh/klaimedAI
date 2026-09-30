"""837P generator + validator tests (spec 1.3)."""

from __future__ import annotations

from decimal import Decimal

from rcm.claims.x12_837 import ControlNumbers, generate_837p, validate_837p
from rcm.edi.segments import tokenize
from tests.claims.factories import RECEIVER, SUBMITTER, build_claim


def _gen() -> str:
    return generate_837p(
        build_claim(),
        submitter=SUBMITTER,
        receiver=RECEIVER,
        control=ControlNumbers(),
    )


def test_generated_837p_is_valid() -> None:
    assert validate_837p(_gen()) == []


def test_envelope_and_required_segments_present() -> None:
    tags = [s.tag for s in tokenize(_gen())]
    for required in ("ISA", "GS", "ST", "BHT", "CLM", "HI", "SV1", "SE", "GE", "IEA"):
        assert required in tags, f"missing {required}"


def test_clm_total_equals_sum_of_lines() -> None:
    segs = {s.tag: s for s in tokenize(_gen())}
    assert Decimal(segs["CLM"].get(2)) == Decimal("270.00")


def test_billing_provider_uses_own_npi_and_ein() -> None:
    segs = tokenize(_gen())
    billing = next(s for s in segs if s.tag == "NM1" and s.get(1) == "85")
    assert billing.get(9) == "1234567893"  # NPI (they attest to accuracy)
    ein = next(s for s in segs if s.tag == "REF" and s.get(1) == "EI")
    assert ein.get(2) == "741234567"


def test_service_lines_have_diagnosis_pointers() -> None:
    for s in tokenize(_gen()):
        if s.tag == "SV1":
            assert s.get(7), "SV1 missing diagnosis pointer"


def test_se_segment_count_is_correct() -> None:
    # validate_837p already checks this, but assert directly for clarity.
    assert "SE count" not in " ".join(validate_837p(_gen()))


def test_member_id_appears_in_subscriber_loop() -> None:
    segs = tokenize(_gen())
    il = next(s for s in segs if s.tag == "NM1" and s.get(1) == "IL")
    assert il.get(9) == "W123456789"


def test_validator_flags_tampered_total() -> None:
    edi = _gen().replace("CLM*PCN00001*270.00", "CLM*PCN00001*999.00")
    problems = validate_837p(edi)
    assert any("CLM total" in p for p in problems)
