"""X12 835 parser tests (spec 0.1: parse the corpus with zero errors)."""

from __future__ import annotations

import glob
from decimal import Decimal
from pathlib import Path

from rcm.edi.x12_835 import parse_835, parse_file, remittance_to_denials

# A minimal but realistic 835 fragment: one denied claim, one service line,
# a line-level CAS (CO-50 medical necessity) with a -25 modifier present.
SAMPLE = (
    "N1*PR*AETNA~"
    "CLP*PCN00001*22*180.00*0*0*12*9876543210*11~"
    "NM1*QC*1*DOE*JANE****MI*123456789~"
    "SVC*HC:99214:25*180.00*0**1~"
    "DTM*472*20260115~"
    "CAS*CO*50*180.00~"
)


def test_parses_payer_and_claim() -> None:
    remit = parse_835(SAMPLE)
    assert remit.payer_name == "AETNA"
    assert len(remit.claims) == 1
    claim = remit.claims[0]
    assert claim.patient_control_number == "PCN00001"
    assert claim.total_charge == Decimal("180.00")
    assert claim.total_paid == Decimal("0")


def test_parses_service_line_cpt_and_modifiers() -> None:
    svc = parse_835(SAMPLE).claims[0].service_lines[0]
    assert svc.cpt_code == "99214"
    assert svc.modifiers == ("25",)
    assert svc.units == 1
    assert svc.charge == Decimal("180.00")


def test_extracts_denial_row_with_carc_and_group() -> None:
    denials = remittance_to_denials(parse_835(SAMPLE))
    assert len(denials) == 1
    d = denials[0]
    assert d.carc_code == "50"
    assert d.group_code == "CO"
    assert d.denied_amount == Decimal("180.00")
    assert d.cpt_code == "99214"
    assert d.modifiers == ("25",)
    assert d.payer_name == "AETNA"


def test_claim_level_cas_produces_denial_without_cpt() -> None:
    text = (
        "N1*PR*CIGNA~"
        "CLP*PCN2*22*120.00*0*0*12*555*11~"
        "CAS*CO*16*120.00~"
    )
    denials = remittance_to_denials(parse_835(text))
    assert len(denials) == 1
    assert denials[0].carc_code == "16"
    assert denials[0].cpt_code is None
    assert denials[0].line_number is None


def test_zero_amount_adjustments_are_not_denials() -> None:
    text = (
        "N1*PR*UHC~"
        "CLP*PCN3*1*100.00*100.00*0*12*777*11~"
        "SVC*HC:99213*100.00*100.00**1~"
        "CAS*CO*45*0~"  # contractual write-down of $0 — not a denial
    )
    assert remittance_to_denials(parse_835(text)) == []


def test_sample_corpus_parses_with_zero_errors() -> None:
    root = Path(__file__).resolve().parent.parent.parent
    files = glob.glob(str(root / "data" / "samples" / "*.sample.835"))
    assert files, "run scripts/gen_synthetic_835.py first"
    total = 0
    for path in files:
        rows = parse_file(path)  # raises X12Error on any malformed segment
        total += len(rows)
    assert total > 0
