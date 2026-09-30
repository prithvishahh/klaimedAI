"""Offline clearinghouse simulator (spec 1.4).

Lets the full round trip — submit 837P -> 277CA ack -> 835 remittance — run and
be tested with no external account. It mirrors what Availity/Office Ally do:

  * validate the 837P front-end; accept it (277CA A2) or reject it (277CA A3);
  * for an accepted, corrected claim, later return an 835 showing it PAID.

A real adapter replaces this class (same :class:`Clearinghouse` Protocol) with
an SFTP/API transport; the pipeline code above it does not change.
"""

from __future__ import annotations

from decimal import Decimal

from rcm.claims.x12_837 import validate_837p
from rcm.clearinghouse.base import SubmissionReceipt
from rcm.clearinghouse.x12_277 import ClaimAck, build_277ca
from rcm.edi.segments import Segment, tokenize

_ELEM = "*"
_SEG = "~"


def _find(segments: list[Segment], tag: str, e1: str | None = None) -> Segment | None:
    for s in segments:
        if s.tag == tag and (e1 is None or s.get(1) == e1):
            return s
    return None


def _build_835_paid(control_number: str, payer_name: str, total: Decimal) -> str:
    """A minimal 835 marking one claim fully paid (no CAS -> no denial rows)."""
    segs = [
        _ELEM.join(["N1", "PR", payer_name or "PAYER"]),
        # CLP: status 1 = processed as primary; paid == charge, patient resp 0.
        _ELEM.join(
            ["CLP", control_number, "1", f"{total:.2f}", f"{total:.2f}", "0",
             "12", f"SIM{control_number}", "11"]
        ),
    ]
    return _SEG.join(segs) + _SEG


class SimulatedClearinghouse:
    """A test/offline clearinghouse. ``pay=True`` returns paid remittances."""

    name = "simulated"

    def __init__(self, *, pay: bool = True) -> None:
        self._pay = pay
        # control_number -> (payer_name, total) for accepted claims.
        self._accepted: dict[str, tuple[str, Decimal]] = {}

    def submit(self, edi_837p: str) -> SubmissionReceipt:
        problems = validate_837p(edi_837p)
        segments = tokenize(edi_837p)
        clm = _find(segments, "CLM")
        control = clm.get(1) if clm else "UNKNOWN"

        if problems:
            ack = ClaimAck.reject(control, "; ".join(problems))
            return SubmissionReceipt(
                control_number=control,
                accepted=False,
                ack_277ca=build_277ca([ack]),
                acks=(ack,),
                errors=tuple(problems),
            )

        payer = _find(segments, "NM1", "PR")
        payer_name = payer.get(3) if payer else ""
        total = Decimal(clm.get(2) or "0") if clm else Decimal("0")
        self._accepted[control] = (payer_name, total)
        ack = ClaimAck.accept(control)
        return SubmissionReceipt(
            control_number=control,
            accepted=True,
            ack_277ca=build_277ca([ack]),
            acks=(ack,),
        )

    def remittance(self, control_number: str) -> str | None:
        if not self._pay or control_number not in self._accepted:
            return None
        payer_name, total = self._accepted[control_number]
        return _build_835_paid(control_number, payer_name, total)
