"""X12 837P (Professional) generator + validator (spec 1.3).

Turns a corrected :class:`Claim837` into a well-formed 837P EDI transaction that
a clearinghouse will accept without a front-end rejection. We generate the
segments a clearinghouse actually validates:

  ISA/GS/ST/BHT envelope · 1000A submitter · 1000B receiver ·
  2000A/2010AA billing provider (+ EIN) · 2000B/SBR subscriber ·
  2010BA subscriber name/member ID · 2010BB payer ·
  2300 CLM (+ HI diagnoses) · 2400 LX/SV1 service lines (+ DTP dates) ·
  SE/GE/IEA trailers with correct segment counts.

``validate_837p`` is our own front-end check: it re-parses the output and
asserts the structural invariants (SE count, CLM total = sum of line charges,
every line has a diagnosis pointer, required loops present). The generator must
always produce output that passes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from rcm.claims.model import Claim837
from rcm.edi.segments import tokenize

_ELEM = "*"
_SUB = ":"
_SEG = "~"

# Diagnosis qualifiers: principal (ABK) then secondary (ABF) for ICD-10-CM.
_DX_PRINCIPAL = "ABK"
_DX_SECONDARY = "ABF"


@dataclass(frozen=True, slots=True)
class Submitter:
    name: str
    etin: str  # electronic transmitter id


@dataclass(frozen=True, slots=True)
class Receiver:
    name: str
    etin: str


@dataclass(frozen=True, slots=True)
class ControlNumbers:
    interchange: str = "000000001"
    group: str = "1"
    transaction: str = "0001"


def _amt(value: Decimal) -> str:
    return f"{value:.2f}"


class _Writer:
    def __init__(self) -> None:
        self._segments: list[str] = []

    def add(self, tag: str, *elements: str) -> None:
        parts = [tag, *elements]
        # Trim trailing empty elements for cleanliness (X12-legal).
        while len(parts) > 1 and parts[-1] == "":
            parts.pop()
        self._segments.append(_ELEM.join(parts))

    def count(self) -> int:
        return len(self._segments)

    def render(self) -> str:
        return _SEG.join(self._segments) + _SEG


def generate_837p(
    claim: Claim837,
    *,
    submitter: Submitter,
    receiver: Receiver,
    control: ControlNumbers | None = None,
    created: datetime | None = None,
) -> str:
    """Serialize ``claim`` to an 837P EDI string."""
    control = control or ControlNumbers()
    created = created or datetime(2026, 1, 20, 12, 0)
    ddate = created.strftime("%Y%m%d")
    dtime = created.strftime("%H%M")
    prov = claim.billing_provider
    sub = claim.subscriber
    payer = claim.payer
    diagnoses = claim.diagnoses()
    dx_index = {dx: i + 1 for i, dx in enumerate(diagnoses)}  # 1-based HI pointers

    # --- Transaction body (ST..SE), counted for SE01 ---
    body = _Writer()
    body.add("ST", "837", control.transaction, "005010X222A1")
    body.add("BHT", "0019", "00", claim.control_number, ddate, dtime, "CH")

    # 1000A submitter / 1000B receiver
    body.add("NM1", "41", "2", submitter.name, "", "", "", "", "46", submitter.etin)
    body.add("PER", "IC", submitter.name, "TE", "0000000000")
    body.add("NM1", "40", "2", receiver.name, "", "", "", "", "46", receiver.etin)

    # 2000A billing provider HL
    body.add("HL", "1", "", "20", "1")
    body.add("NM1", "85", "2", prov.organization_name, "", "", "", "", "XX", prov.npi)
    body.add("N3", prov.address.line1)
    body.add("N4", prov.address.city, prov.address.state, prov.address.zip_code)
    body.add("REF", "EI", prov.tax_id)  # employer identification number (EIN)

    # 2000B subscriber HL (subscriber is the patient here)
    body.add("HL", "2", "1", "22", "0")
    body.add("SBR", "P", "18", "", "", "", "", "", "", "CI")
    body.add(
        "NM1", "IL", "1", sub.last_name, sub.first_name, "", "", "", "MI", sub.member_id
    )
    body.add("DMG", "D8", sub.dob.strftime("%Y%m%d"), sub.gender)
    # 2010BB payer
    body.add("NM1", "PR", "2", payer.name, "", "", "", "", "PI", payer.payer_id)

    # 2300 claim
    pos_composite = _SUB.join([claim.place_of_service, "B", "1"])
    body.add("CLM", claim.control_number, _amt(claim.total_charge), "", "", pos_composite,
             "Y", "A", "Y", "Y")
    # HI diagnoses: first principal (ABK), remainder secondary (ABF).
    if diagnoses:
        hi_elems = []
        for i, dx in enumerate(diagnoses):
            qual = _DX_PRINCIPAL if i == 0 else _DX_SECONDARY
            hi_elems.append(_SUB.join([qual, dx.replace(".", "")]))
        body.add("HI", *hi_elems)

    # 2400 service lines
    for line in claim.lines:
        body.add("LX", str(line.line_number))
        svc = _SUB.join(["HC", line.cpt_code, *line.modifiers])
        pointers = _SUB.join(
            str(dx_index[dx]) for dx in line.diagnosis_codes if dx in dx_index
        )
        body.add(
            "SV1", svc, _amt(line.charge_amount), "UN", str(line.units), "", "", pointers
        )
        body.add("DTP", "472", "D8", line.dos.strftime("%Y%m%d"))

    # SE: segment count includes ST and SE themselves.
    se_count = body.count() + 1
    body.add("SE", str(se_count), control.transaction)

    # --- Envelope ---
    out = _Writer()
    out.add(
        "ISA", "00", " " * 10, "00", " " * 10, "ZZ", f"{submitter.etin:<15}",
        "ZZ", f"{receiver.etin:<15}", created.strftime("%y%m%d"), dtime, "^",
        "00501", control.interchange, "0", "P", _SUB,
    )
    out.add("GS", "HC", submitter.etin, receiver.etin, ddate, dtime, control.group,
            "X", "005010X222A1")
    # Splice the counted body between GS and GE.
    body_segments = body.render()
    envelope_head = out.render()  # ends with ISA~GS~
    trailer = _Writer()
    trailer.add("GE", "1", control.group)
    trailer.add("IEA", "1", control.interchange)
    return envelope_head + body_segments + trailer.render()


# --- Validator (our own front-end acceptance check) ------------------------


def validate_837p(edi: str) -> list[str]:
    """Return a list of structural problems. Empty list == valid."""
    problems: list[str] = []
    try:
        segments = tokenize(edi)
    except Exception as exc:  # noqa: BLE001
        return [f"untokenizable: {exc}"]

    tags = [s.tag for s in segments]
    by_tag = {s.tag: s for s in segments}

    for required in ("ISA", "GS", "ST", "BHT", "CLM", "SE", "GE", "IEA"):
        if required not in tags:
            problems.append(f"missing required segment {required}")

    # Billing provider + EIN, subscriber, payer loops.
    if not any(s.tag == "NM1" and s.get(1) == "85" for s in segments):
        problems.append("missing billing provider (NM1*85)")
    if not any(s.tag == "REF" and s.get(1) == "EI" for s in segments):
        problems.append("missing billing provider tax id (REF*EI)")
    if not any(s.tag == "NM1" and s.get(1) == "IL" for s in segments):
        problems.append("missing subscriber (NM1*IL)")
    if not any(s.tag == "NM1" and s.get(1) == "PR" for s in segments):
        problems.append("missing payer (NM1*PR)")

    # SE segment count (ST..SE inclusive) must match the actual count.
    if "ST" in tags and "SE" in tags:
        st_idx = tags.index("ST")
        se_idx = tags.index("SE")
        actual = se_idx - st_idx + 1
        declared = by_tag["SE"].get(1)
        if declared != str(actual):
            problems.append(f"SE count {declared} != actual {actual}")

    # CLM total charge must equal the sum of SV1 line charges.
    sv1 = [s for s in segments if s.tag == "SV1"]
    if not sv1:
        problems.append("no service lines (SV1)")
    line_total = sum((Decimal(s.get(2) or "0") for s in sv1), Decimal("0"))
    if "CLM" in by_tag:
        clm_total = Decimal(by_tag["CLM"].get(2) or "0")
        if clm_total != line_total:
            problems.append(f"CLM total {clm_total} != sum of lines {line_total}")

    # Every service line must carry at least one diagnosis pointer (SV1 elem 7).
    for s in sv1:
        if not s.get(7):
            problems.append(f"service line {s.get(1)} has no diagnosis pointer")

    return problems


def is_valid_837p(edi: str) -> bool:
    return not validate_837p(edi)


__all__ = [
    "Submitter",
    "Receiver",
    "ControlNumbers",
    "generate_837p",
    "validate_837p",
    "is_valid_837p",
]
