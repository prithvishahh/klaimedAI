"""Test factories for the write-path domain model (synthetic, fake PHI)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rcm.claims.model import (
    Address,
    BillingProvider,
    Claim837,
    Payer,
    ServiceLine,
    Subscriber,
)
from rcm.claims.x12_837 import Receiver, Submitter

SUBMITTER = Submitter(name="RCM CLEARING", etin="RCM0001")
RECEIVER = Receiver(name="AVAILITY", etin="AV0001")


def build_claim() -> Claim837:
    """A realistic denied derm claim (fake PHI) with two service lines."""
    provider = BillingProvider(
        npi="1234567893",
        organization_name="BEACHHEAD DERMATOLOGY",
        tax_id="741234567",
        address=Address("100 MAIN ST", "AUSTIN", "TX", "78701"),
        taxonomy_code="207N00000X",
    )
    subscriber = Subscriber(
        member_id="W123456789",
        last_name="DOE",
        first_name="JANE",
        dob=date(1985, 3, 2),
        gender="F",
    )
    payer = Payer(name="AETNA", payer_id="60054")
    lines = (
        ServiceLine(
            line_number=1,
            cpt_code="99213",
            charge_amount=Decimal("120.00"),
            units=1,
            dos=date(2026, 1, 15),
            diagnosis_codes=("E11.9",),
        ),
        ServiceLine(
            line_number=2,
            cpt_code="11100",
            charge_amount=Decimal("150.00"),
            units=1,
            dos=date(2026, 1, 15),
            modifiers=(),
            diagnosis_codes=("D48.5",),
        ),
    )
    return Claim837(
        control_number="PCN00001",
        billing_provider=provider,
        subscriber=subscriber,
        payer=payer,
        lines=lines,
        chart_text="type 2 diabetes E11.9; neoplasm uncertain behavior D48.5",
    )
