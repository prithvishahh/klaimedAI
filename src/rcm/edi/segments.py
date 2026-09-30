"""X12 EDI tokenizer and the parsed remittance data structures.

X12 files are segment/element/sub-element delimited. Delimiters are declared in
the fixed-width ISA header when present; otherwise we fall back to the common
defaults (``*`` element, ``:`` sub-element, ``~`` segment).

These dataclasses are the *pure* parse result — no database, no ORM — so the
835 parser can be unit-tested against real remittance text with zero infra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class X12Error(ValueError):
    """Raised when an 835 cannot be parsed."""


@dataclass(frozen=True, slots=True)
class Delimiters:
    element: str = "*"
    sub_element: str = ":"
    segment: str = "~"

    @classmethod
    def detect(cls, text: str) -> Delimiters:
        """Detect delimiters from the ISA header, else return defaults."""
        if text.startswith("ISA") and len(text) >= 106:
            return cls(element=text[3], sub_element=text[104], segment=text[105])
        return cls()


@dataclass(frozen=True, slots=True)
class Segment:
    tag: str
    elements: tuple[str, ...]

    def get(self, idx: int, default: str = "") -> str:
        """1-based element accessor (X12 convention: CLP01 is elements[0])."""
        return self.elements[idx - 1] if 0 < idx <= len(self.elements) else default


def tokenize(text: str) -> list[Segment]:
    """Split raw 835 text into segments. Whitespace between segments is ignored."""
    delims = Delimiters.detect(text)
    segments: list[Segment] = []
    for raw in text.split(delims.segment):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(delims.element)
        segments.append(Segment(tag=parts[0], elements=tuple(parts[1:])))
    if not segments:
        raise X12Error("no segments found")
    return segments


# --- Parsed remittance structures -------------------------------------------


@dataclass(frozen=True, slots=True)
class Adjustment:
    """A CAS adjustment: group code + CARC + amount (+ quantity)."""

    group_code: str  # CO/PR/OA/PI
    carc_code: str  # Claim Adjustment Reason Code, e.g. "50"
    amount: Decimal
    quantity: Decimal = Decimal("0")


@dataclass(slots=True)
class ServicePayment:
    """One SVC service line plus its line-level adjustments.

    Mutable: line-level CAS adjustments are appended as they are parsed after
    the SVC segment.
    """

    cpt_code: str
    modifiers: tuple[str, ...]
    charge: Decimal
    paid: Decimal
    units: int
    adjustments: list[Adjustment] = field(default_factory=list)


@dataclass(slots=True)
class ClaimPayment:
    """One CLP claim payment: status, money, and its adjustments/service lines."""

    patient_control_number: str
    claim_status: str
    total_charge: Decimal
    total_paid: Decimal
    patient_responsibility: Decimal
    payer_claim_control_number: str
    claim_adjustments: list[Adjustment] = field(default_factory=list)
    service_lines: list[ServicePayment] = field(default_factory=list)


@dataclass(slots=True)
class Remittance:
    """A parsed 835: the payer and its claim payments."""

    payer_name: str
    claims: list[ClaimPayment] = field(default_factory=list)
