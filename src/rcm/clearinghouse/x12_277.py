"""X12 277CA (Claim Acknowledgment) — build + parse.

The 277CA is the clearinghouse/payer's *front-end* response: was the claim
accepted for adjudication, or rejected before it ever adjudicated? This is a
different thing from a denial — a denial (CAS in an 835) means the claim WAS
adjudicated and then denied. A 277CA rejection means it never got that far
(bad format, missing field, unknown member). Tracking the two separately keeps
the pipeline honest about where a claim actually is.

Health Care Claim Status Category codes used here:
  * ``A1``/``A2`` — received / accepted for processing  -> accepted
  * ``A3``/``A7`` — returned / rejected                 -> rejected

NB: build and parse here are a **matched pair** — a compact, internally
consistent 277CA sufficient to model accept/reject offline. Parsing real
payer-issued 277CA (full hierarchical STC loops) is a later hardening task.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

_ELEM = "*"
_SUB = ":"
_SEG = "~"

_ACCEPTED_CATEGORIES = frozenset({"A1", "A2"})


@dataclass(frozen=True, slots=True)
class ClaimAck:
    """One claim's acknowledgment status."""

    control_number: str  # the submitted claim control number (CLM01)
    category: str  # A1/A2 accepted, A3/A7 rejected
    status_code: str  # health care claim status code (free-form here)
    message: str = ""

    @property
    def accepted(self) -> bool:
        return self.category in _ACCEPTED_CATEGORIES

    @classmethod
    def accept(cls, control_number: str, message: str = "Accepted for processing") -> ClaimAck:
        return cls(control_number, "A2", "20", message)

    @classmethod
    def reject(cls, control_number: str, message: str) -> ClaimAck:
        return cls(control_number, "A3", "21", message)


def build_277ca(acks: list[ClaimAck], *, created: datetime | None = None) -> str:
    """Serialize claim acknowledgments to a compact 277CA transaction."""
    created = created or datetime(2026, 1, 21, 9, 0)
    ddate = created.strftime("%Y%m%d")
    dtime = created.strftime("%H%M")
    segs: list[str] = []
    segs.append(_ELEM.join(["ST", "277", "0001", "005010X214"]))
    segs.append(_ELEM.join(["BHT", "0085", "08", "277CA0001", ddate, dtime, "TH"]))
    for ack in acks:
        segs.append(_ELEM.join(["TRN", "2", ack.control_number]))
        status = _SUB.join([ack.category, ack.status_code])
        # STC01 = category:status, STC02 = free-form message (simplified).
        segs.append(_ELEM.join(["STC", status, ack.message]))
    segs.append(_ELEM.join(["SE", str(len(segs) + 1), "0001"]))
    return _SEG.join(segs) + _SEG


def parse_277ca(text: str) -> list[ClaimAck]:
    """Parse a 277CA (built by :func:`build_277ca`) into claim acknowledgments."""
    acks: list[ClaimAck] = []
    control: str | None = None
    for raw in text.split(_SEG):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(_ELEM)
        tag = parts[0]
        if tag == "TRN":
            control = parts[2] if len(parts) > 2 else None
        elif tag == "STC" and control is not None:
            composite = (parts[1] if len(parts) > 1 else "").split(_SUB)
            category = composite[0] if composite else ""
            status_code = composite[1] if len(composite) > 1 else ""
            message = parts[2] if len(parts) > 2 else ""
            acks.append(ClaimAck(control, category, status_code, message))
            control = None
    return acks
