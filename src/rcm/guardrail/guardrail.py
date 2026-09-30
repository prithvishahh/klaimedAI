"""The compliance guardrail — hard code, not a prompt (spec §7).

This is the single largest risk control in the company. A model optimizing for
collections will learn that adding a ``-25`` modifier or bumping an E/M level
gets claims paid. That is the False Claims Act — treble damages, federal,
criminal. "The model did it" has never been a defense.

Therefore every outbound claim/appeal is diffed against the original and must
pass this function BEFORE it can leave the system. It is:

  * **pure** — no I/O, no database, no network, no model calls;
  * **deterministic** — same inputs always give the same verdict;
  * **unbypassable** — there is no flag, prompt, or config that disables a rule;
  * **unit-tested with adversarial cases** — see tests/guardrail/test_adversarial.py.

The system is deliberately *incapable* of the most profitable form of fraud.
That is a feature we sell: "Our system architecturally cannot upcode. Here's the
audit log."

ALLOWED without human review (do NOT change codes):
  demographic corrections · attaching documents already in the chart ·
  correcting payer ID / routing · resubmitting the identical claim ·
  drafting an appeal LETTER · citing payer policy / LCD text.

DENIED (BLOCK -> human coder queue):
  any change to CPT/HCPCS/ICD/modifier/units/charge/E&M that could increase
  reimbursement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from rcm.guardrail.em_levels import em_level
from rcm.guardrail.icd_chart import icd_supported_by_chart

HUMAN_CODER = "human_coder"


class Decision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Result of a guardrail evaluation."""

    decision: Decision
    rule: str | None = None
    reason: str | None = None
    route_to: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.BLOCK


ALLOW = Verdict(Decision.ALLOW)


def _block(rule: str, reason: str) -> Verdict:
    return Verdict(Decision.BLOCK, rule=rule, reason=reason, route_to=HUMAN_CODER)


@dataclass(frozen=True, slots=True)
class GuardrailLine:
    """The guardrail's view of a single service line.

    Decoupled from the ORM on purpose: the guardrail depends on no I/O layer, so
    it can be tested with plain values and can never be affected by a database or
    model regression.
    """

    line_number: int
    cpt_code: str
    modifiers: frozenset[str] = field(default_factory=frozenset)
    icd_codes: frozenset[str] = field(default_factory=frozenset)
    units: int = 1
    charge_amount: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class GuardrailClaim:
    """The guardrail's view of a claim plus the encounter chart it draws on."""

    lines: tuple[GuardrailLine, ...]
    chart_text: str = ""

    def cpt_set(self) -> frozenset[str]:
        return frozenset(line.cpt_code for line in self.lines)

    def max_em_level(self) -> int:
        return max((em_level(line.cpt_code) for line in self.lines), default=0)

    def by_line_number(self) -> dict[int, GuardrailLine]:
        return {line.line_number: line for line in self.lines}


def guardrail(original: GuardrailClaim, proposed: GuardrailClaim) -> Verdict:
    """Return ALLOW or a BLOCK verdict for ``proposed`` relative to ``original``.

    Enforced BEFORE any outbound claim/appeal leaves the system. Runs as a pure
    function. Cannot be bypassed by any agent.
    """
    orig_lines = original.by_line_number()
    prop_lines = proposed.by_line_number()

    # A line added or removed changes what is billed -> human review.
    if set(orig_lines) != set(prop_lines):
        return _block("line_set_changed", "Service-line set changed (line added/removed)")

    # RULE 1 — Procedure codes are immutable by agents (claim-level set check
    # mirrors the spec; per-line check below catches same-set swaps).
    if original.cpt_set() != proposed.cpt_set():
        return _block("cpt_changed", "CPT/HCPCS set changed")

    for line_no, orig in orig_lines.items():
        prop = prop_lines[line_no]

        # RULE 1 (per line) — procedure code cannot change on a given line.
        if orig.cpt_code != prop.cpt_code:
            return _block("cpt_changed", f"CPT changed on line {line_no}")

        # RULE 2 — Modifiers are code changes. Additions especially (the -25/-59
        # upcoding vector). Any change to the modifier set blocks.
        if orig.modifiers != prop.modifiers:
            return _block("modifier_changed", f"Modifier set changed on line {line_no}")

        # RULE 3 — Diagnosis codes: additions allowed ONLY if the ICD already
        # appears in the chart text. Never invented.
        for icd in prop.icd_codes - orig.icd_codes:
            if not icd_supported_by_chart(icd, original.chart_text):
                return _block(
                    "icd_not_in_chart",
                    f"ICD {icd} added on line {line_no} but not documented in chart",
                )

        # RULE 4 — Units may never increase.
        if prop.units > orig.units:
            return _block("units_increased", f"Units increased on line {line_no}")

        # RULE 5 — Charge amount may never increase.
        if prop.charge_amount > orig.charge_amount:
            return _block("charge_increased", f"Charge increased on line {line_no}")

    # RULE 6 — E/M level may never be raised (99213 -> 99214, etc.).
    if proposed.max_em_level() > original.max_em_level():
        return _block("em_upcoded", "E/M level raised")

    return ALLOW
