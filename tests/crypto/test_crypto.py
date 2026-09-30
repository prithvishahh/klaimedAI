"""PHI encryption tests: round-trip, uniqueness, tamper-detection, fail-closed."""

from __future__ import annotations

import base64

import pytest

from rcm.core import crypto


def test_round_trip() -> None:
    for value in ["Jane Doe", "1985-03-02", "", "chart: dx E11.9, plan: metformin"]:
        assert crypto.decrypt(crypto.encrypt(value)) == value


def test_ciphertext_is_nondeterministic() -> None:
    # Fresh nonce per call -> identical plaintext yields different ciphertext.
    assert crypto.encrypt("Jane Doe") != crypto.encrypt("Jane Doe")


def test_ciphertext_is_not_plaintext() -> None:
    token = crypto.encrypt("SSN 123-45-6789")
    assert "123-45-6789" not in token


def test_tampered_ciphertext_is_rejected() -> None:
    token = crypto.encrypt("Jane Doe")
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[-1] ^= 0x01  # flip a bit in the tag
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(tampered)


def test_aad_binding() -> None:
    token = crypto.encrypt("Jane Doe", aad=b"patient.name_enc")
    assert crypto.decrypt(token, aad=b"patient.name_enc") == "Jane Doe"
    # Wrong associated data must fail (ciphertext bound to its column).
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(token, aad=b"encounter.chart_text_enc")


def test_generate_key_is_32_bytes() -> None:
    assert len(base64.urlsafe_b64decode(crypto.generate_key())) == 32


def test_bad_key_length_is_rejected() -> None:
    with pytest.raises(crypto.CryptoError):
        crypto._decode_master_key(base64.urlsafe_b64encode(b"too-short").decode())
