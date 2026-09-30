"""PHI de-identification tests (fail-closed boundary)."""

from __future__ import annotations

import pytest

from rcm.llm.deident import PHILeakError, assert_deidentified, deidentify, residual_phi


def test_strips_structured_identifiers() -> None:
    text = (
        "Patient Jane Doe, DOB 03/02/1985, SSN 123-45-6789, member 987654321, "
        "phone 555-123-4567, jane@example.com seen on 2026-01-15."
    )
    clean = deidentify(text, names=("Jane Doe",))
    assert "Jane Doe" not in clean
    assert "123-45-6789" not in clean
    assert "987654321" not in clean
    assert "jane@example.com" not in clean
    assert "555-123-4567" not in clean
    assert residual_phi(clean) == []


def test_assert_deidentified_passes_on_clean_text() -> None:
    assert_deidentified("Denial CO-50: medical necessity not established for [ID].")


def test_assert_deidentified_fails_closed_on_residual_phi() -> None:
    with pytest.raises(PHILeakError):
        assert_deidentified("member id 123456789 not on file")


def test_error_never_contains_the_phi() -> None:
    try:
        assert_deidentified("ssn 123-45-6789")
    except PHILeakError as exc:
        assert "123-45-6789" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected PHILeakError")
