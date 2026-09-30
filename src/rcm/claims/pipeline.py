"""Guardrail-gated outbound pipeline (spec 1.1 + 1.2 + 1.3).

This is the single doorway to the outside world. Nothing becomes an 837P without
first passing the guardrail. The rule is absolute:

    proposed claim  --> guardrail(original, proposed)
                        ├── BLOCK  -> record guardrail_block, route to human
                        │            coder, emit NO EDI. Raise GuardrailBlocked.
                        └── ALLOW  -> generate 837P, append audit record.

The corrections agent (data-only) will always pass, but the gate does not trust
that — it diffs every outbound claim against the original and enforces the six
rules in code. That is what makes the system architecturally incapable of
upcoding on the write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rcm.claims.corrections import CorrectionContext, CorrectionResult, propose_correction
from rcm.claims.model import Claim837
from rcm.claims.x12_837 import (
    ControlNumbers,
    Receiver,
    Submitter,
    generate_837p,
    validate_837p,
)
from rcm.clearinghouse.base import Clearinghouse, SubmissionReceipt
from rcm.guardrail.guardrail import Verdict, guardrail

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class GuardrailBlocked(Exception):
    """Raised when the guardrail refuses an outbound claim. Carries the verdict."""

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        super().__init__(
            f"guardrail BLOCK [{verdict.rule}]: {verdict.reason} -> {verdict.route_to}"
        )


@dataclass(frozen=True, slots=True)
class OutboundClaim:
    """A cleared, ready-to-submit claim: the EDI plus provenance."""

    edi_837p: str
    verdict: Verdict
    strategy: str | None


def _audit(
    session: Session | None,
    *,
    actor: str,
    action: str,
    entity_id: str,
    after: dict[str, object] | None,
) -> None:
    if session is None:
        return
    # Imported lazily so the pipeline is usable without a database.
    from rcm.audit.log import record_action

    record_action(
        session,
        actor=actor,
        action=action,
        entity_type="claim",
        entity_id=entity_id,
        after=after,
    )


def prepare_outbound_837p(
    original: Claim837,
    proposed: Claim837,
    *,
    submitter: Submitter,
    receiver: Receiver,
    control: ControlNumbers | None = None,
    strategy: str | None = None,
    actor: str = "corrections_agent",
    session: Session | None = None,
) -> OutboundClaim:
    """Gate ``proposed`` through the guardrail, then generate its 837P.

    Raises :class:`GuardrailBlocked` (and records a guardrail_block) if the
    proposed claim would change any code. On success, appends an audit record.
    """
    verdict = guardrail(original.to_guardrail_claim(), proposed.to_guardrail_claim())

    if verdict.blocked:
        if session is not None:
            from rcm.audit.log import record_guardrail_block

            record_guardrail_block(
                session,
                agent=actor,
                rule_violated=verdict.rule or "unknown",
                attempted_change={
                    "control_number": proposed.control_number,
                    "rule": verdict.rule,
                    "reason": verdict.reason,
                },
            )
        raise GuardrailBlocked(verdict)

    edi = generate_837p(
        proposed, submitter=submitter, receiver=receiver, control=control
    )
    problems = validate_837p(edi)
    if problems:  # generator invariant — should never happen for a cleared claim
        raise ValueError(f"generated 837P failed validation: {problems}")

    _audit(
        session,
        actor=actor,
        action="generate_837p",
        entity_id=proposed.control_number,
        after={"strategy": strategy, "total_charge": str(proposed.total_charge)},
    )
    return OutboundClaim(edi_837p=edi, verdict=verdict, strategy=strategy)


def correct_and_prepare(
    original: Claim837,
    carc_code: str,
    ctx: CorrectionContext,
    *,
    submitter: Submitter,
    receiver: Receiver,
    control: ControlNumbers | None = None,
    session: Session | None = None,
) -> tuple[CorrectionResult, OutboundClaim | None]:
    """Full easy-class flow: correct → guardrail gate → 837P.

    Returns ``(result, outbound)``. If the denial is not correctable (out of
    class, or no verified data), ``outbound`` is ``None`` and ``result.route_to``
    says where it goes instead.
    """
    result = propose_correction(original, carc_code, ctx)
    if not result.correctable or result.corrected_claim is None:
        return result, None

    outbound = prepare_outbound_837p(
        original,
        result.corrected_claim,
        submitter=submitter,
        receiver=receiver,
        control=control,
        strategy=result.strategy,
        session=session,
    )
    return result, outbound


def submit_outbound(
    outbound: OutboundClaim,
    clearinghouse: Clearinghouse,
    *,
    actor: str = "corrections_agent",
    session: Session | None = None,
) -> SubmissionReceipt:
    """Submit a cleared 837P to the clearinghouse and audit the submission.

    Returns the 277CA acknowledgment. A rejection (``accepted=False``) is a
    *front-end* rejection — the claim never reached adjudication — which is
    distinct from a denial (an 835 CAS on an adjudicated claim).
    """
    receipt = clearinghouse.submit(outbound.edi_837p)
    _audit(
        session,
        actor=actor,
        action="submit_837p",
        entity_id=receipt.control_number,
        after={
            "accepted": receipt.accepted,
            "clearinghouse": clearinghouse.name,
            "errors": list(receipt.errors),
        },
    )
    return receipt
