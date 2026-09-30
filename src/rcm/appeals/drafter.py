"""Appeal letter drafters (spec 1.5).

A drafter turns the denial + retrieved policy criteria + chart evidence into an
appeal-letter *body*. Two implementations behind one Protocol:

  * ``TemplateDrafter`` — deterministic, offline, no model. Cites each retrieved
    policy and maps documented chart evidence to it. A solid, testable baseline.
  * ``ClaudeDrafter`` — production quality via Claude Opus. **PHI-safe**: the
    chart is de-identified and checked (fail-closed) before it is ever sent; the
    prompt body is never logged (only a hash is retained).

Neither drafter can change a code — they emit prose. Patient identifiers are NOT
in the body; the agent templates the letter header locally (see agent.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rcm.appeals.model import AppealContext, RetrievedPolicy
from rcm.guardrail.icd_chart import icd_supported_by_chart

_SENTENCE = re.compile(r"[^.;\n]+")


@dataclass(frozen=True, slots=True)
class DraftedBody:
    body: str
    model: str | None = None
    prompt_hash: str | None = None


def _chart_evidence(chart_text: str, icd_codes: tuple[str, ...]) -> list[str]:
    """Sentences in the chart that document one of the billed diagnoses."""
    evidence: list[str] = []
    for raw in _SENTENCE.findall(chart_text):
        sentence = raw.strip()
        if not sentence:
            continue
        if any(icd_supported_by_chart(icd, sentence) for icd in icd_codes):
            evidence.append(sentence)
    return evidence


class Drafter(Protocol):
    def draft(
        self, context: AppealContext, policies: list[RetrievedPolicy]
    ) -> DraftedBody:
        ...


class TemplateDrafter:
    """Deterministic appeal body that cites the payer's own criteria."""

    def draft(
        self, context: AppealContext, policies: list[RetrievedPolicy]
    ) -> DraftedBody:
        claim = context.claim
        cpts = ", ".join(sorted({ln.cpt_code for ln in claim.lines}))
        icds = tuple(sorted({icd for ln in claim.lines for icd in ln.diagnosis_codes}))
        payer = claim.payer.name

        parts: list[str] = [
            f"We are writing to formally appeal the denial of the above claim "
            f"(CARC {context.carc_code}), which was denied as not medically "
            f"necessary. The service billed (CPT {cpts}) was medically necessary "
            f"and supported by the documentation on file.",
        ]

        if policies:
            for pol in policies:
                cite = f"“{pol.title}”" + (f" ({pol.url})" if pol.url else "")
                parts.append(
                    f"Per {payer}'s own coverage policy {cite}, the applicable "
                    f"criteria are:\n{pol.text.strip()}"
                )
        else:
            parts.append(
                "The service meets generally accepted standards of medical "
                "necessity for the documented condition."
            )

        evidence = _chart_evidence(claim.chart_text, icds)
        if evidence:
            bullets = "\n".join(f"  - {e}" for e in evidence)
            parts.append(
                "The following documented clinical facts satisfy these criteria:\n"
                + bullets
            )

        parts.append(
            f"Accordingly, we respectfully request reconsideration and payment of "
            f"this claim as billed (CPT {cpts}; diagnoses {', '.join(icds)}). No "
            f"change to the billed codes is requested — only reconsideration of "
            f"medical necessity."
        )
        return DraftedBody(body="\n\n".join(parts))


class ClaudeDrafter:
    """Production drafter using Claude Opus. De-identifies the chart first."""

    def __init__(self) -> None:
        from rcm.core.config import get_settings

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set; use TemplateDrafter for offline drafting"
            )
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.drafting_model

    def draft(
        self, context: AppealContext, policies: list[RetrievedPolicy]
    ) -> DraftedBody:
        from rcm.llm.client import prompt_hash
        from rcm.llm.deident import assert_deidentified, deidentify

        claim = context.claim
        cpts = ", ".join(sorted({ln.cpt_code for ln in claim.lines}))
        icds = ", ".join(sorted({i for ln in claim.lines for i in ln.diagnosis_codes}))

        # PHI-safe: strip patient identifiers from the chart before sending.
        safe_chart = deidentify(
            claim.chart_text, names=(claim.subscriber.last_name, claim.subscriber.first_name)
        )
        assert_deidentified(safe_chart)

        policy_block = "\n\n".join(f"[{p.title}]\n{p.text}" for p in policies) or "(none)"
        prompt = (
            "Draft the BODY of a formal medical-necessity appeal letter. Cite the "
            "payer's coverage criteria below verbatim where possible and map the "
            "documented clinical facts to each criterion. Do NOT suggest any change "
            "to the billed codes — argue medical necessity for the codes as billed. "
            "Output only the letter body (no header, no signature).\n\n"
            f"Denial: CARC {context.carc_code} (not medically necessary)\n"
            f"Billed CPT: {cpts}\nDiagnoses: {icds}\n\n"
            f"Payer coverage criteria:\n{policy_block}\n\n"
            f"De-identified clinical documentation:\n{safe_chart}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        body = "".join(b.text for b in response.content if b.type == "text")
        return DraftedBody(body=body, model=self._model, prompt_hash=prompt_hash(prompt))
