"""The demo scenario: one practice's denial backlog (synthetic, fake PHI).

Five original claims that were submitted and came back denied for five different
reasons, so the console shows the full range of what Klaimed does:

  PCN10001  CO-140  wrong member id        -> data fix, resubmit
  PCN10002  CO-16   name mismatch on file  -> data fix, resubmit
  PCN10003  CO-27   coverage terminated    -> rebill to the active payer
  PCN10004  CO-50   not medically necessary-> appeal citing payer policy
  PCN10005  CO-97   bundled (E/M + proc)   -> escalate to a human coder

The originals are the Claim837 objects a practice's PM system holds. The uploaded
835 (rendered from ``sample_835()``) is the payer's denial file. The console
matches them by claim control number, exactly as production would.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rcm.claims.corrections import CorrectionContext
from rcm.claims.model import (
    Address,
    BillingProvider,
    Claim837,
    Payer,
    ServiceLine,
    Subscriber,
)
from rcm.claims.x12_837 import Receiver, Submitter

SUBMITTER = Submitter(name="KLAIMED", etin="KLMD01")
RECEIVER = Receiver(name="AVAILITY", etin="AV0001")

_PROVIDER = BillingProvider(
    npi="1234567893",
    organization_name="BEACHHEAD DERMATOLOGY",
    tax_id="741234567",
    address=Address("100 MAIN ST", "AUSTIN", "TX", "78701"),
)

AETNA = Payer(name="AETNA", payer_id="60054")
UHC = Payer(name="UNITEDHEALTHCARE", payer_id="87726")
CIGNA = Payer(name="CIGNA", payer_id="62308")


@dataclass(frozen=True, slots=True)
class DenialCase:
    """One denied claim: the original, the denial, and the verified fix (if any)."""

    control_number: str
    carc: str
    reason: str  # plain-English payer reason
    denied_amount: Decimal
    original: Claim837
    context: CorrectionContext  # verified correction values (empty if not fixable)
    plan: str  # what Klaimed does, in one line
    denial_date: date  # when the payer denied it (drives the appeal deadline)


def _claim(cn: str, sub: Subscriber, payer: Payer, line: ServiceLine, chart: str = "") -> Claim837:
    return Claim837(
        control_number=cn,
        billing_provider=_PROVIDER,
        subscriber=sub,
        payer=payer,
        lines=(line,),
        chart_text=chart,
    )


CASES: tuple[DenialCase, ...] = (
    DenialCase(
        control_number="PCN10001",
        carc="140",
        reason="Patient/Insured health identification number and name do not match.",
        denied_amount=Decimal("180.00"),
        original=_claim(
            "PCN10001",
            Subscriber("W000000000", "DOE", "JANE", date(1985, 3, 2), "F"),
            AETNA,
            ServiceLine(1, "99213", Decimal("180.00"), 1, date(2026, 1, 15),
                        diagnosis_codes=("L70.0",)),
        ),
        context=CorrectionContext(verified_member_id="W123456789"),
        plan="Correct the member ID from eligibility, resubmit. Codes untouched.",
        denial_date=date(2026, 4, 10),
    ),
    DenialCase(
        control_number="PCN10002",
        carc="16",
        reason="Claim/service lacks information: subscriber last name does not match.",
        denied_amount=Decimal("250.00"),
        original=_claim(
            "PCN10002",
            Subscriber("W223344556", "SMITH", "MICHAEL", date(1978, 11, 9), "M"),
            UHC,
            ServiceLine(1, "99214", Decimal("250.00"), 1, date(2026, 1, 18),
                        diagnosis_codes=("L40.0",)),
        ),
        context=CorrectionContext(corrected_last_name="SMYTHE"),
        plan="Correct the last name to match the payer's record, resubmit.",
        denial_date=date(2026, 2, 20),
    ),
    DenialCase(
        control_number="PCN10003",
        carc="27",
        reason="Expenses incurred after coverage terminated (wrong payer on file).",
        denied_amount=Decimal("180.00"),
        original=_claim(
            "PCN10003",
            Subscriber("W334455667", "NAIR", "PRIYA", date(1990, 6, 21), "F"),
            CIGNA,
            ServiceLine(1, "99213", Decimal("180.00"), 1, date(2026, 1, 12),
                        diagnosis_codes=("L70.0",)),
        ),
        context=CorrectionContext(corrected_payer=AETNA),
        plan="Rebill to the patient's active payer (Aetna) verified via eligibility.",
        denial_date=date(2026, 6, 25),
    ),
    DenialCase(
        control_number="PCN10004",
        carc="50",
        reason="These services are not deemed a medical necessity by the payer.",
        denied_amount=Decimal("220.00"),
        original=_claim(
            "PCN10004",
            Subscriber("W445566778", "KIM", "DAVID", date(1966, 2, 4), "M"),
            AETNA,
            ServiceLine(1, "11102", Decimal("220.00"), 1, date(2026, 1, 20),
                        diagnosis_codes=("D48.5",)),
            chart="8mm pigmented lesion, asymmetric borders, recent change in size and "
                  "color. Biopsy performed to rule out malignancy (D48.5).",
        ),
        context=CorrectionContext(),  # not a data fix -> appeal path
        plan="Appeal citing the payer's own coverage policy and the chart evidence.",
        denial_date=date(2026, 7, 10),
    ),
    DenialCase(
        control_number="PCN10005",
        carc="97",
        reason="Benefit for this service is bundled into another service (E/M + procedure).",
        denied_amount=Decimal("180.00"),
        original=_claim(
            "PCN10005",
            Subscriber("W556677889", "GOMEZ", "LISA", date(1982, 9, 30), "F"),
            AETNA,
            ServiceLine(1, "99213", Decimal("180.00"), 1, date(2026, 1, 22),
                        diagnosis_codes=("L57.0",)),
        ),
        context=CorrectionContext(),  # bundling is the danger zone -> human coder
        plan="Escalate to a certified coder. We never auto-touch bundling (fraud risk).",
        denial_date=date(2026, 5, 15),
    ),
)

BY_CN: dict[str, DenialCase] = {c.control_number: c for c in CASES}


def sample_835() -> str:
    """Render the backlog as one X12 835 remittance the parser can ingest."""
    segs: list[str] = ["ST*835*0001", "BPR*I*1830*C*ACH*CCP", "TRN*1*0000012345*1234567890"]
    for c in CASES:
        line = c.original.lines[0]
        segs.append(f"N1*PR*{c.original.payer.name}")
        # CLP: control number, status 4 (denied), charge, paid 0, pat resp 0, payer ctrl
        segs.append(
            f"CLP*{c.control_number}*4*{line.charge_amount}*0*0*MC*{c.control_number}CH"
        )
        mods = ":".join(("HC", line.cpt_code, *line.modifiers))
        segs.append(f"SVC*{mods}*{line.charge_amount}*0**{line.units}")
        segs.append(f"CAS*CO*{c.carc}*{c.denied_amount}")
    segs.append("SE*0*0001")
    return "~".join(segs) + "~\n"
