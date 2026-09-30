"""CARC routing tests (spec 0.2)."""

from __future__ import annotations

from rcm.enums import TriageClass
from rcm.taxonomy.carc import classify_carc


def test_maps_known_families() -> None:
    assert classify_carc("16") is TriageClass.ADMINISTRATIVE
    assert classify_carc("27") is TriageClass.ELIGIBILITY
    assert classify_carc("197") is TriageClass.AUTHORIZATION
    assert classify_carc("50") is TriageClass.MEDICAL_NECESSITY
    assert classify_carc("97") is TriageClass.BUNDLING
    assert classify_carc("204") is TriageClass.LEGITIMATE


def test_tolerates_group_prefix() -> None:
    assert classify_carc("CO-50") is TriageClass.MEDICAL_NECESSITY
    assert classify_carc("PR-204") is TriageClass.LEGITIMATE


def test_unknown_carc_is_never_silently_recoverable() -> None:
    assert classify_carc("99999") is TriageClass.UNKNOWN
