"""Claim domain model for the outbound (write) path.

This is the richer, in-memory representation of a professional claim — enough to
(a) generate a valid X12 837P and (b) be diffed against the original by the
guardrail. It is the "corrected claim" the corrections agent produces and the
837P generator serializes.

The source of a claim's full data is the originally-submitted 837 (or the PM
system), NOT the 835 remittance — the 835 only tells us a claim was denied and
why. So Phase 1 works on this model, built from the original claim.

Nothing here does I/O; ``to_guardrail_claim`` bridges to the pure guardrail so
every outbound claim can be checked before it leaves the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from rcm.guardrail.guardrail import GuardrailClaim, GuardrailLine


@dataclass(frozen=True, slots=True)
class Address:
    line1: str
    city: str
    state: str
    zip_code: str


@dataclass(frozen=True, slots=True)
class BillingProvider:
    """2010AA billing provider — submits under ITS OWN NPI (it attests)."""

    npi: str
    organization_name: str
    tax_id: str  # EIN
    address: Address
    taxonomy_code: str | None = None


@dataclass(frozen=True, slots=True)
class Subscriber:
    """2010BA subscriber (the insured). Member ID is the payer's identifier."""

    member_id: str
    last_name: str
    first_name: str
    dob: date
    gender: str  # M | F | U
    address: Address | None = None


@dataclass(frozen=True, slots=True)
class Payer:
    """2010BB payer."""

    name: str
    payer_id: str


@dataclass(frozen=True, slots=True)
class ServiceLine:
    """2400 service line. Diagnosis codes are resolved (mapped to HI pointers)."""

    line_number: int
    cpt_code: str
    charge_amount: Decimal
    units: int
    dos: date
    place_of_service: str = "11"  # office
    modifiers: tuple[str, ...] = ()
    diagnosis_codes: tuple[str, ...] = ()  # ICD-10 supporting this line


@dataclass(frozen=True, slots=True)
class Claim837:
    """A professional claim ready for correction / 837P generation."""

    control_number: str  # patient control number (CLM01)
    billing_provider: BillingProvider
    subscriber: Subscriber
    payer: Payer
    lines: tuple[ServiceLine, ...]
    place_of_service: str = "11"
    # The encounter chart (PHI). Only used to let the guardrail verify that any
    # added ICD is documented — corrections never add ICDs, so usually unused.
    chart_text: str = field(default="", repr=False)

    @property
    def total_charge(self) -> Decimal:
        return sum((ln.charge_amount for ln in self.lines), Decimal("0"))

    def diagnoses(self) -> tuple[str, ...]:
        """Claim-level ordered, de-duplicated diagnosis list (for the HI segment)."""
        ordered: list[str] = []
        for line in self.lines:
            for dx in line.diagnosis_codes:
                if dx not in ordered:
                    ordered.append(dx)
        return tuple(ordered)

    def to_guardrail_claim(self) -> GuardrailClaim:
        """Project to the guardrail's view so it can be diffed vs the original."""
        return GuardrailClaim(
            lines=tuple(
                GuardrailLine(
                    line_number=ln.line_number,
                    cpt_code=ln.cpt_code,
                    modifiers=frozenset(ln.modifiers),
                    icd_codes=frozenset(ln.diagnosis_codes),
                    units=ln.units,
                    charge_amount=ln.charge_amount,
                )
                for ln in self.lines
            ),
            chart_text=self.chart_text,
        )
