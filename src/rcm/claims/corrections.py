"""Corrections agent (spec 1.2) — the easy class only.

Handles the highest-ROI, lowest-risk denials: administrative (CO-16 missing
info, CO-140 patient/insured ID) and eligibility mismatches (CO-27, CO-31). It
**fixes data and resubmits** — corrected member ID, demographics, or payer
routing — and makes **no coding changes**: the service lines are copied verbatim.

By construction this agent cannot touch CPT/HCPCS/ICD/modifier/units/charge. The
guardrail is still run on its output (defense in depth — see pipeline.py); if a
future change ever mutated a code, the outbound path would BLOCK.

Anything outside the easy class (bundling, medical necessity, unknown) is refused
and routed to a human coder / the appeal path — never silently "corrected".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from rcm.claims.model import Claim837, Payer
from rcm.enums import AppealStrategy, TriageClass
from rcm.taxonomy.carc import classify_carc

HUMAN_CODER = "human_coder"
APPEAL = "appeal"

_EASY_CLASSES = frozenset({TriageClass.ADMINISTRATIVE, TriageClass.ELIGIBILITY})


@dataclass(frozen=True, slots=True)
class FieldChange:
    """A single data correction. ``before``/``after`` may be PHI (encrypted in
    the audit log; redacted in logs)."""

    field: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class CorrectionContext:
    """Verified correct values from eligibility (270/271) or the patient record.

    The corrections agent only applies values supplied here — it never invents
    data (that would be its own kind of fraud). Absent context, it refuses.
    """

    verified_member_id: str | None = None
    corrected_payer: Payer | None = None
    corrected_last_name: str | None = None
    corrected_first_name: str | None = None
    corrected_dob: date | None = None


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    correctable: bool
    reason: str
    strategy: str | None = None
    corrected_claim: Claim837 | None = None
    changes: tuple[FieldChange, ...] = ()
    route_to: str | None = None


def _route_for(triage_class: TriageClass) -> str:
    # Bundling is the danger zone; medical necessity is an appeal, not a fix.
    if triage_class is TriageClass.MEDICAL_NECESSITY:
        return APPEAL
    return HUMAN_CODER


def propose_correction(
    original: Claim837, carc_code: str, ctx: CorrectionContext
) -> CorrectionResult:
    """Propose a data-only correction for an easy-class denial.

    Returns ``correctable=False`` (with a route) when the denial is out of class
    or no verified correction is available.
    """
    triage_class = classify_carc(carc_code)
    if triage_class not in _EASY_CLASSES:
        return CorrectionResult(
            correctable=False,
            reason=f"{carc_code} is {triage_class.value}, not an easy-class fix",
            route_to=_route_for(triage_class),
        )

    sub = original.subscriber
    changes: list[FieldChange] = []
    new_member_id = sub.member_id
    new_last = sub.last_name
    new_first = sub.first_name
    new_dob = sub.dob

    if ctx.verified_member_id and ctx.verified_member_id != sub.member_id:
        changes.append(FieldChange("subscriber.member_id", sub.member_id, ctx.verified_member_id))
        new_member_id = ctx.verified_member_id
    if ctx.corrected_last_name and ctx.corrected_last_name != sub.last_name:
        changes.append(FieldChange("subscriber.last_name", sub.last_name, ctx.corrected_last_name))
        new_last = ctx.corrected_last_name
    if ctx.corrected_first_name and ctx.corrected_first_name != sub.first_name:
        changes.append(
            FieldChange("subscriber.first_name", sub.first_name, ctx.corrected_first_name)
        )
        new_first = ctx.corrected_first_name
    if ctx.corrected_dob and ctx.corrected_dob != sub.dob:
        changes.append(
            FieldChange("subscriber.dob", sub.dob.isoformat(), ctx.corrected_dob.isoformat())
        )
        new_dob = ctx.corrected_dob

    new_payer = original.payer
    if ctx.corrected_payer and ctx.corrected_payer != original.payer:
        changes.append(
            FieldChange("payer", original.payer.payer_id, ctx.corrected_payer.payer_id)
        )
        new_payer = ctx.corrected_payer

    if not changes:
        return CorrectionResult(
            correctable=False,
            reason="no verified correction available for this denial",
            route_to=HUMAN_CODER,
        )

    corrected = replace(
        original,
        subscriber=replace(
            sub,
            member_id=new_member_id,
            last_name=new_last,
            first_name=new_first,
            dob=new_dob,
        ),
        payer=new_payer,
        # lines are intentionally NOT passed to replace() -> copied verbatim.
    )

    strategy = (
        AppealStrategy.ELIGIBILITY_REBILL.value
        if new_payer is not original.payer
        else AppealStrategy.CORRECTED_CLAIM.value
    )
    return CorrectionResult(
        correctable=True,
        reason=f"data correction ({len(changes)} field(s))",
        strategy=strategy,
        corrected_claim=corrected,
        changes=tuple(changes),
    )
