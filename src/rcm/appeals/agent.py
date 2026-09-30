"""APPEAL agent (spec 1.5) — medical-necessity appeals.

Flow:  guard class  ->  retrieve payer policy (RAG)  ->  draft letter body
       ->  assemble letter with a locally-templated PHI header  ->  audit.

It only handles medical-necessity denials (CO-50/55/167). Everything else is
routed elsewhere (administrative/eligibility -> corrections, bundling -> human
coder, legitimate -> close). It **never changes a code**: the output is a letter
plus the original claim, resubmitted unchanged. ``argued_cpt_codes`` is asserted
identical to the claim's codes so the appeal path can't smuggle in an upcode.

PHI boundary: retrieval uses only public policy text; drafting de-identifies the
chart before any model call (see drafter.py). Patient identifiers appear only in
the letter header, assembled here — never in a model prompt.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from rcm.appeals.drafter import Drafter, TemplateDrafter
from rcm.appeals.model import MEDICAL_NECESSITY, AppealContext, AppealDraft
from rcm.appeals.retriever import PolicyRetriever
from rcm.enums import TriageClass
from rcm.taxonomy.carc import classify_carc

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_ROUTE = {
    TriageClass.ADMINISTRATIVE: "corrections",
    TriageClass.ELIGIBILITY: "corrections",
    TriageClass.AUTHORIZATION: "authorization",
    TriageClass.BUNDLING: "human_coder",
    TriageClass.LEGITIMATE: "close",
    TriageClass.UNKNOWN: "human_coder",
}


def _cpt_codes(context: AppealContext) -> tuple[str, ...]:
    return tuple(sorted({ln.cpt_code for ln in context.claim.lines}))


def _retrieval_query(context: AppealContext) -> str:
    claim = context.claim
    cpts = " ".join(sorted({ln.cpt_code for ln in claim.lines}))
    icds = " ".join(sorted({i for ln in claim.lines for i in ln.diagnosis_codes}))
    return f"medical necessity coverage {context.specialty} CPT {cpts} {icds}"


def _assemble_letter(
    context: AppealContext, body: str, cited: tuple[str, ...]
) -> str:
    claim = context.claim
    sub = claim.subscriber
    prov = claim.billing_provider
    dos = ", ".join(sorted({ln.dos.isoformat() for ln in claim.lines}))
    citations = "; ".join(cited) if cited else "None"
    return (
        f"{date.today().isoformat()}\n\n"
        f"{claim.payer.name}\nAttn: Appeals Department\n\n"
        f"RE: Appeal of Claim Denial (Medical Necessity)\n"
        f"Patient: {sub.last_name}, {sub.first_name}\n"
        f"Member ID: {sub.member_id}\n"
        f"Claim #: {claim.control_number}\n"
        f"Date(s) of Service: {dos}\n"
        f"Amount in Dispute: ${context.denied_amount:.2f}\n\n"
        f"To Whom It May Concern:\n\n{body}\n\n"
        f"Sincerely,\n{prov.organization_name}\nNPI: {prov.npi}\n\n"
        f"Policies cited: {citations}"
    )


def draft_appeal(
    context: AppealContext,
    *,
    retriever: PolicyRetriever,
    drafter: Drafter | None = None,
    k: int = 3,
    actor: str = "appeal_agent",
    session: Session | None = None,
) -> AppealDraft:
    """Draft a medical-necessity appeal, or refuse + route if out of class."""
    triage_class = classify_carc(context.carc_code)
    if triage_class is not TriageClass.MEDICAL_NECESSITY:
        return AppealDraft(
            appealable=False,
            reason=f"{context.carc_code} is {triage_class.value}, not a medical-necessity appeal",
            route_to=_ROUTE.get(triage_class, "human_coder"),
        )

    drafter = drafter or TemplateDrafter()
    cpt_codes = _cpt_codes(context)
    policies = retriever.retrieve(_retrieval_query(context), cpt_codes=cpt_codes, k=k)
    cited = tuple(p.title for p in policies)

    drafted = drafter.draft(context, policies)
    letter = _assemble_letter(context, drafted.body, cited)

    # Safety property (by construction): the appeal argues for exactly the billed
    # codes — it produces a letter, never a modified claim, so no code can change.
    # ``argued_cpt_codes`` below is the claim's own codes; the resubmission is the
    # original claim unchanged plus this letter.

    if session is not None:
        from rcm.audit.log import record_action

        record_action(
            session,
            actor=actor,
            action="draft_appeal",
            entity_type="claim",
            entity_id=context.claim.control_number,
            after={
                "strategy": MEDICAL_NECESSITY,
                "cited_policies": list(cited),
                "argued_cpt_codes": list(cpt_codes),
            },
            model=drafted.model,
            prompt_hash_value=drafted.prompt_hash,
        )

    return AppealDraft(
        appealable=True,
        reason=f"medical-necessity appeal citing {len(cited)} policy(ies)",
        strategy=MEDICAL_NECESSITY,
        letter_text=letter,
        cited_policies=cited,
        model=drafted.model,
        prompt_hash=drafted.prompt_hash,
        argued_cpt_codes=cpt_codes,
    )
