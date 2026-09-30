"""Appeal domain types (spec 1.5).

An appeal produces a **letter**, never a claim change. Medical-necessity denials
are argued by citing the payer's own coverage criteria (LCD / policy) and mapping
documented chart evidence to each criterion — not by touching a code. The
guardrail explicitly allows letter drafting; this path has no code-mutation
capability at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from rcm.claims.model import Claim837
from rcm.enums import AppealStrategy


@dataclass(frozen=True, slots=True)
class AppealContext:
    """Everything needed to draft an appeal for one denied claim."""

    claim: Claim837  # the original claim (unchanged — appeals never edit codes)
    carc_code: str
    denied_amount: Decimal
    specialty: str = "dermatology"


@dataclass(frozen=True, slots=True)
class RetrievedPolicy:
    """A coverage policy retrieved from the index (public text — no PHI)."""

    title: str
    text: str
    url: str | None
    score: float
    cpt_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppealDraft:
    """The drafted appeal. ``letter_text`` contains PHI (encrypted at rest)."""

    appealable: bool
    reason: str
    strategy: str | None = None
    letter_text: str | None = None
    cited_policies: tuple[str, ...] = ()
    model: str | None = None
    prompt_hash: str | None = None
    route_to: str | None = None
    # The billed codes the appeal argues for — asserted identical to the claim,
    # so the appeal can never smuggle in a code change.
    argued_cpt_codes: tuple[str, ...] = field(default=())


MEDICAL_NECESSITY = AppealStrategy.MEDICAL_NECESSITY.value
