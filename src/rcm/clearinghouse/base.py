"""Clearinghouse interface (spec 1.4).

We integrate at the clearinghouse (Availity, Office Ally, ...), not with 900
payers directly. Real clearinghouses exchange X12 batches over SFTP/API:
we drop an 837P, they return a 277CA acknowledgment, and later an 835
remittance. This Protocol captures that contract; a real Availity/Office Ally
adapter and the offline :class:`SimulatedClearinghouse` both implement it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rcm.clearinghouse.x12_277 import ClaimAck


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    """The result of submitting an 837P: the 277CA and its parsed acks."""

    control_number: str
    accepted: bool
    ack_277ca: str  # raw 277CA transaction
    acks: tuple[ClaimAck, ...] = ()
    errors: tuple[str, ...] = field(default=())


@runtime_checkable
class Clearinghouse(Protocol):
    """Submit claims and retrieve remittances."""

    name: str

    def submit(self, edi_837p: str) -> SubmissionReceipt:
        """Submit an 837P; return the 277CA acknowledgment (accept/reject)."""
        ...

    def remittance(self, control_number: str) -> str | None:
        """Return the 835 remittance for an accepted claim, or None if pending."""
        ...
