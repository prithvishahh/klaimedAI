"""X12 835 (Electronic Remittance Advice) parser — the foundation of Phase 0.

The 835 is the payer's response to a claim: what was paid, what was denied, and
why. Denials live here. We parse:

  * CLP — claim payment (status, charge, paid, patient responsibility)
  * CAS — claim adjustment segments (group code + CARC/amount triplets)
  * SVC — service payment (procedure code, modifiers, charge, paid, units)
  * NM1*PR — payer name

and turn every non-zero adjustment into a *denial row* (a CARC on an amount that
was not paid). This is our primary input signal.

CLI:  python -m rcm.edi.x12_835 data/samples/*.sample.835
"""

from __future__ import annotations

import glob
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from rcm.edi.segments import (
    Adjustment,
    ClaimPayment,
    Delimiters,
    Remittance,
    Segment,
    ServicePayment,
    X12Error,
    tokenize,
)


def _dec(value: str) -> Decimal:
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise X12Error(f"invalid numeric value: {value!r}") from exc


def _parse_cas(seg: Segment) -> list[Adjustment]:
    """CAS = group code + up to 6 (reason, amount, quantity) triplets."""
    group = seg.get(1)
    adjustments: list[Adjustment] = []
    # Elements after the group code come in triplets: reason, amount, [qty].
    body = seg.elements[1:]
    for i in range(0, len(body), 3):
        reason = body[i] if i < len(body) else ""
        if not reason:
            continue
        amount = _dec(body[i + 1]) if i + 1 < len(body) else Decimal("0")
        qty = _dec(body[i + 2]) if i + 2 < len(body) else Decimal("0")
        adjustments.append(
            Adjustment(group_code=group, carc_code=reason, amount=amount, quantity=qty)
        )
    return adjustments


def _parse_svc(seg: Segment, sub_delim: str) -> ServicePayment:
    """SVC01 is a composite: qualifier:CPT:mod1:mod2:... (e.g. HC:99213:25)."""
    composite = seg.get(1).split(sub_delim)
    cpt = composite[1] if len(composite) > 1 else ""
    modifiers = tuple(m for m in composite[2:] if m)
    units_raw = seg.get(5)
    units = int(_dec(units_raw)) if units_raw else 1
    return ServicePayment(
        cpt_code=cpt,
        modifiers=modifiers,
        charge=_dec(seg.get(2)),
        paid=_dec(seg.get(3)),
        units=units,
    )


def parse_835(text: str) -> Remittance:
    """Parse raw 835 text into a :class:`Remittance`. Pure — no I/O."""
    delims = Delimiters.detect(text)
    segments = tokenize(text)

    payer_name = ""
    remittance = Remittance(payer_name="")
    current_claim: ClaimPayment | None = None
    current_service: ServicePayment | None = None

    for seg in segments:
        tag = seg.tag
        if tag == "N1" and seg.get(1) == "PR":  # payer name (835 uses N1*PR)
            payer_name = seg.get(2)
        elif tag == "NM1" and seg.get(1) == "PR":  # some payers use NM1*PR
            payer_name = seg.get(3)
        elif tag == "CLP":
            current_claim = ClaimPayment(
                patient_control_number=seg.get(1),
                claim_status=seg.get(2),
                total_charge=_dec(seg.get(3)),
                total_paid=_dec(seg.get(4)),
                patient_responsibility=_dec(seg.get(5)),
                payer_claim_control_number=seg.get(7),
            )
            remittance.claims.append(current_claim)
            current_service = None
        elif tag == "SVC":
            if current_claim is None:
                raise X12Error("SVC segment before any CLP")
            current_service = _parse_svc(seg, delims.sub_element)
            current_claim.service_lines.append(current_service)
        elif tag == "CAS":
            adjustments = _parse_cas(seg)
            if current_service is not None:
                current_service.adjustments.extend(adjustments)
            elif current_claim is not None:
                current_claim.claim_adjustments.extend(adjustments)
            else:
                raise X12Error("CAS segment before any CLP")
        elif tag == "LX":
            current_service = None  # new service-line loop begins

    remittance.payer_name = payer_name
    return remittance


# --- Denial extraction ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DenialRow:
    """A denial flattened from the remittance — the parser's product (spec 0.1)."""

    patient_control_number: str
    payer_claim_control_number: str
    payer_name: str
    carc_code: str
    group_code: str
    denied_amount: Decimal
    cpt_code: str | None
    modifiers: tuple[str, ...]
    line_number: int | None


def remittance_to_denials(remittance: Remittance) -> list[DenialRow]:
    """Flatten a remittance into denial rows (one per non-zero adjustment)."""
    rows: list[DenialRow] = []
    for claim in remittance.claims:
        # Claim-level adjustments (no service line attached).
        for adj in claim.claim_adjustments:
            if adj.amount == 0:
                continue
            rows.append(
                DenialRow(
                    patient_control_number=claim.patient_control_number,
                    payer_claim_control_number=claim.payer_claim_control_number,
                    payer_name=remittance.payer_name,
                    carc_code=adj.carc_code,
                    group_code=adj.group_code,
                    denied_amount=adj.amount,
                    cpt_code=None,
                    modifiers=(),
                    line_number=None,
                )
            )
        # Service-line adjustments.
        for idx, svc in enumerate(claim.service_lines, start=1):
            for adj in svc.adjustments:
                if adj.amount == 0:
                    continue
                rows.append(
                    DenialRow(
                        patient_control_number=claim.patient_control_number,
                        payer_claim_control_number=claim.payer_claim_control_number,
                        payer_name=remittance.payer_name,
                        carc_code=adj.carc_code,
                        group_code=adj.group_code,
                        denied_amount=adj.amount,
                        cpt_code=svc.cpt_code,
                        modifiers=svc.modifiers,
                        line_number=idx,
                    )
                )
    return rows


def parse_file(path: str) -> list[DenialRow]:
    with open(path, encoding="utf-8") as fh:
        return remittance_to_denials(parse_835(fh.read()))


def _main(argv: list[str]) -> int:
    paths: list[str] = []
    for arg in argv[1:]:
        paths.extend(glob.glob(arg))
    if not paths:
        print("usage: python -m rcm.edi.x12_835 <835 file(s) or glob>", file=sys.stderr)
        return 2

    total = 0
    errors = 0
    for path in sorted(paths):
        try:
            denials = parse_file(path)
        except X12Error as exc:
            errors += 1
            print(f"ERROR {path}: {exc}", file=sys.stderr)
            continue
        total += len(denials)
        recoverable = sum(d.denied_amount for d in denials if d.group_code == "CO")
        print(
            f"{path}: {len(denials)} denial rows  "
            f"(CO recoverable ${recoverable:,.2f})"
        )
    print(f"\nparsed {len(paths)} file(s): {total} denial rows, {errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
