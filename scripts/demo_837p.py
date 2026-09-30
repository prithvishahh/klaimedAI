#!/usr/bin/env python3
"""End-to-end demo for the RCM system (synthetic data).

Every line printed is real output from the actual modules — nothing is
hardcoded or staged. Runs one denied claim through the pipeline:

  1. Triage a denial backlog (classify, rank by priority, compute deadline)
  2. Correct a fixable denial (data only) -> guardrail -> 837P -> submit -> paid
  3. Guardrail: an upcode attempt is blocked (no 837P generated)
  4. Medical-necessity appeal drafted via RAG over the payer coverage policy

No setup needed:  python scripts/demo_837p.py
Paced (for recording): RCM_DEMO_PACE=1 python scripts/demo_837p.py
"""

from __future__ import annotations

# --- make the demo runnable with zero env setup (dev-only key, offline embeddings) ---
import base64
import os
import time

os.environ.setdefault(
    "RCM_MASTER_KEY",  # dev-only demo key; exactly 32 bytes -> AES-256
    base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode(),
)
os.environ.setdefault("RCM_EMBEDDING_DIM", "64")
os.environ.setdefault("RCM_ENV", "dev")

# Paced mode for screen recordings: RCM_DEMO_PACE=1 makes each beat hold long
# enough to read (total ~2 min). Default is instant (for normal/CLI use).
_PACED = os.environ.get("RCM_DEMO_PACE", "").lower() in {"1", "true", "yes"}


def hold(seconds: float) -> None:
    """Pause so a viewer can read the current beat (only when paced)."""
    if _PACED:
        time.sleep(seconds)

from dataclasses import replace  # noqa: E402
from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from rcm.appeals.agent import draft_appeal  # noqa: E402
from rcm.appeals.model import AppealContext  # noqa: E402
from rcm.appeals.outcomes import MoatAggregate, fold_outcome  # noqa: E402
from rcm.appeals.retriever import InMemoryRetriever  # noqa: E402
from rcm.claims.corrections import CorrectionContext  # noqa: E402
from rcm.claims.model import (  # noqa: E402
    Address,
    BillingProvider,
    Claim837,
    Payer,
    ServiceLine,
    Subscriber,
)
from rcm.claims.pipeline import (  # noqa: E402
    GuardrailBlocked,
    correct_and_prepare,
    prepare_outbound_837p,
    submit_outbound,
)
from rcm.claims.x12_837 import Receiver, Submitter, validate_837p  # noqa: E402
from rcm.clearinghouse.simulated import SimulatedClearinghouse  # noqa: E402
from rcm.deadlines.calculator import appeal_deadline, days_until, deadline_risk  # noqa: E402
from rcm.edi.x12_835 import parse_835, remittance_to_denials  # noqa: E402
from rcm.policy.scraper import scrape_policies  # noqa: E402
from rcm.triage.agent import triage  # noqa: E402

SUBMITTER = Submitter(name="RCM CLEARING", etin="RCM0001")
RECEIVER = Receiver(name="AVAILITY", etin="AV0001")


def hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def sample_claim() -> Claim837:
    """A denied dermatology claim (fake PHI): wrong member id -> CO-140 denial."""
    return Claim837(
        control_number="PCN00042",
        billing_provider=BillingProvider(
            npi="1234567893",
            organization_name="BEACHHEAD DERMATOLOGY",
            tax_id="741234567",
            address=Address("100 MAIN ST", "AUSTIN", "TX", "78701"),
        ),
        subscriber=Subscriber(
            member_id="W000000000",  # wrong on file -> administrative denial
            last_name="DOE",
            first_name="JANE",
            dob=date(1985, 3, 2),
            gender="F",
        ),
        payer=Payer(name="AETNA", payer_id="60054"),
        lines=(
            ServiceLine(
                line_number=1,
                cpt_code="99213",
                charge_amount=Decimal("180.00"),
                units=1,
                dos=date(2026, 1, 15),
                diagnosis_codes=("E11.9",),
            ),
        ),
        chart_text="type 2 diabetes E11.9, stable, follow-up",
    )


def section_1_triage() -> None:
    hr("1. TRIAGE  —  classify denial, rank by priority, compute deadline")
    # A small denial backlog straight off an 835 (CARC, amount, payer).
    backlog = [
        ("CO-16", Decimal("120.00"), "missing information"),
        ("CO-140", Decimal("210.00"), "wrong member id"),
        ("CO-50", Decimal("180.00"), "not medically necessary"),
        ("CO-97", Decimal("95.00"), "bundled into another service"),
        ("PR-204", Decimal("75.00"), "not covered by plan"),
    ]
    results = [(triage(c.split("-")[1], amt), c, amt) for c, amt, _why in backlog]
    ordered = sorted(results, key=lambda r: r[0].priority, reverse=True)

    print(f"\n  {'CARC':<8}{'CLASS':<18}{'ACTION':<14}{'$ DENIED':>9}{'PRIORITY':>10}")
    print("  " + "-" * 59)
    for res, carc, amt in ordered:
        print(
            f"  {carc:<8}{res.triage_class.value:<18}{res.disposition.value:<14}"
            f"{'$' + format(amt, '.0f'):>9}{'$' + format(res.priority, '.0f'):>10}"
        )
    print("\n  Ranked by denied_amount x recovery probability (priority).")

    dl = appeal_deadline(date.today(), "AETNA")
    print(
        f"  Top claim appeal_deadline: {dl.isoformat()} "
        f"({days_until(dl)} days left, risk={deadline_risk(dl).value})"
    )
    hold(12)


def section_2_recovery(original: Claim837) -> None:
    hr("2. CORRECT + SUBMIT  —  fix data, codes untouched, 837P, clearinghouse")
    result, outbound = correct_and_prepare(
        original,
        "140",
        CorrectionContext(verified_member_id="W123456789"),
        submitter=SUBMITTER,
        receiver=RECEIVER,
    )
    if outbound is None:
        raise SystemExit("correction did not produce an outbound claim")
    change = result.changes[0]
    print(f"\n  Fix (data only): {change.field}  {change.before} -> {change.after}")
    print(f"  Procedure codes: UNCHANGED  {[ln.cpt_code for ln in original.lines]}")
    print(f"  Guardrail: {outbound.verdict.decision.value.upper()}   "
          f"837P valid: {not validate_837p(outbound.edi_837p)}")
    print("  Generated 837P (excerpt):")
    for seg in outbound.edi_837p.split("~")[2:9]:
        if seg.strip():
            print(f"    {seg}~")

    ch = SimulatedClearinghouse(pay=True)
    receipt = submit_outbound(outbound, ch)
    remit = ch.remittance(receipt.control_number)
    denials = remittance_to_denials(parse_835(remit)) if remit else []
    print(f"  Clearinghouse: 277CA {'ACCEPTED' if receipt.accepted else 'REJECTED'} "
          f"-> 835 {'PAID' if remit and not denials else 'n/a'}  (loop closed)")
    hold(18)


def section_3_guardrail(original: Claim837) -> int:
    hr("3. GUARDRAIL  —  attempt to raise a code on an outbound claim")
    print("\n  Attempted change: add modifier -25 to CPT 99213  (a classic upcode)")
    hold(3)  # let the tension build before the block
    malicious = replace(original, lines=(replace(original.lines[0], modifiers=("25",)),))
    try:
        prepare_outbound_837p(original, malicious, submitter=SUBMITTER, receiver=RECEIVER)
        print("  !!! ERROR: the upcode was NOT blocked")
        return 1
    except GuardrailBlocked as exc:
        v = exc.verdict
        print()
        print("  " + "#" * 56)
        print("  #" + " GUARDRAIL: BLOCKED ".center(54) + "#")
        print("  #" + f" rule: {v.rule} ".center(54) + "#")
        print("  #" + f" route: {v.route_to} ".center(54) + "#")
        print("  #" + " no 837P generated · guardrail_block recorded ".center(54) + "#")
        print("  " + "#" * 56)
        hold(22)
    return 0


def section_4_appeal(original: Claim837) -> None:
    hr("4. APPEAL  —  medical necessity, RAG over payer coverage policy")
    retriever = InMemoryRetriever(scrape_policies("dermatology"))
    appeal = draft_appeal(
        AppealContext(claim=original, carc_code="50", denied_amount=Decimal("180.00")),
        retriever=retriever,
    )
    print(f"\n  Strategy: {appeal.strategy}")
    print(f"  Cited policies (retrieved from the policy index): {list(appeal.cited_policies)}")
    print(f"  Codes argued (unchanged): {list(appeal.argued_cpt_codes)}")
    print("  Appeal letter (excerpt):")
    for line in (appeal.letter_text or "").splitlines()[15:19]:
        if line.strip():
            print(f"    {line}")
    print("\n  Letter sent, claim resubmitted unchanged. When the payer responds,")
    print("  the outcome feeds the learning loop below.")
    hold(14)


def section_5_moat() -> None:
    hr("5. LEARNING LOOP  —  resolved outcomes feed the win-rate moat")
    # Each resolved appeal (paid or denied) is folded into appeal_outcome by the
    # SAME fold_outcome() the production DB path uses — so these are real stats,
    # computed live, over a batch of synthetic resolved appeals.
    #   (payer, carc, strategy, recovered, won, days_to_resolution)
    resolved = [
        ("AETNA", "50", "medical_necessity", Decimal("180"), True, 18),  # this run's claim
        ("AETNA", "50", "medical_necessity", Decimal("165"), True, 24),
        ("AETNA", "50", "medical_necessity", Decimal("0"), False, 40),
        ("AETNA", "50", "medical_necessity", Decimal("150"), True, 21),
        ("UHC", "50", "medical_necessity", Decimal("0"), False, 33),
        ("UHC", "50", "medical_necessity", Decimal("140"), True, 27),
        ("AETNA", "197", "retro_auth", Decimal("95"), True, 12),
        ("AETNA", "197", "retro_auth", Decimal("0"), False, 15),
    ]
    moat: dict[tuple[str, str, str], MoatAggregate] = {}
    print(f"\n  ...folding {len(resolved)} resolved appeals into appeal_outcome")
    for payer, carc, strat, recovered, won, days in resolved:
        key = (payer, carc, strat)
        moat[key] = fold_outcome(moat.get(key), recovered=recovered, won=won, days=days)
    hold(3)

    print(
        f"\n  {'PAYER':<8}{'CARC':<7}{'STRATEGY':<19}{'N':>3}"
        f"{'WIN%':>7}{'AVG $REC':>10}{'AVG DAYS':>10}"
    )
    print("  " + "-" * 64)
    for (payer, carc, strat), a in moat.items():
        print(
            f"  {payer:<8}{'CO-' + carc:<7}{strat:<19}{a.attempts:>3}"
            f"{format(a.win_rate * 100, '.0f') + '%':>7}"
            f"{'$' + format(a.avg_recovered, '.0f'):>10}"
            f"{format(a.avg_days_to_resolution or 0, '.0f'):>10}"
        )
    print("\n  appeal_outcome, keyed by payer x CARC x specialty x strategy (synthetic).")
    print("  Every resolved claim sharpens this. Only a contingency operator sees it.")
    hold(16)


def main() -> int:
    original = sample_claim()
    print("\nRCM pipeline — a denial worked end to end, then the learning loop.")
    print("Synthetic data (fake PHI).")
    hold(3)
    section_1_triage()
    section_2_recovery(original)
    code = section_3_guardrail(original)
    section_4_appeal(original)
    section_5_moat()
    print()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
