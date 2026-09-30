"""CARC (Claim Adjustment Reason Code) -> triage routing (spec §5).

CARCs are a fixed, standardized taxonomy (~400 codes), so most routing can be
hard-coded. This is the triage agent's primary signal. The mapping follows the
spec's denial taxonomy table:

  Administrative / fixable  CO-16, CO-11, CO-140      High recoverability
  Eligibility               CO-27, CO-31              Medium
  Authorization             CO-197                    Medium
  Medical necessity         CO-50, CO-55, CO-167      Medium (the hard ones)
  Bundling / coding         CO-97, CO-234, CO-236     DANGER — human coder ALWAYS
  Legitimate                PR-204, CO-96, duplicate  No — close, don't appeal

Any CARC not in the table maps to UNKNOWN (route to human review), never silently
to a recoverable class.
"""

from __future__ import annotations

from rcm.enums import TriageClass

# CARC code (without group prefix) -> triage class.
_CARC_TO_CLASS: dict[str, TriageClass] = {
    # Administrative / fixable
    "16": TriageClass.ADMINISTRATIVE,  # missing information
    "11": TriageClass.ADMINISTRATIVE,  # dx/procedure mismatch
    "140": TriageClass.ADMINISTRATIVE,  # patient/insured health ID
    "125": TriageClass.ADMINISTRATIVE,  # submission/billing error
    "4": TriageClass.ADMINISTRATIVE,  # procedure inconsistent with modifier
    # Eligibility
    "27": TriageClass.ELIGIBILITY,  # expenses after coverage terminated
    "31": TriageClass.ELIGIBILITY,  # patient cannot be identified
    "26": TriageClass.ELIGIBILITY,  # expenses before coverage
    "177": TriageClass.ELIGIBILITY,  # patient not eligible
    # Authorization
    "197": TriageClass.AUTHORIZATION,  # precert/authorization absent
    "198": TriageClass.AUTHORIZATION,  # precert/auth exceeded
    # Medical necessity — the hard, valuable ones
    "50": TriageClass.MEDICAL_NECESSITY,  # not deemed medically necessary
    "55": TriageClass.MEDICAL_NECESSITY,  # experimental/investigational
    "167": TriageClass.MEDICAL_NECESSITY,  # diagnosis not covered
    "56": TriageClass.MEDICAL_NECESSITY,  # not proven effective
    # Bundling / coding — DANGER ZONE. Fixing usually means changing a modifier.
    "97": TriageClass.BUNDLING,  # payment included in another service
    "234": TriageClass.BUNDLING,  # not eligible for separate payment
    "236": TriageClass.BUNDLING,  # procedure/modifier inconsistent (NCCI)
    "59": TriageClass.BUNDLING,  # multiple/concurrent procedures
    # Legitimate — close, don't waste the appeal
    "96": TriageClass.LEGITIMATE,  # non-covered charge
    "204": TriageClass.LEGITIMATE,  # not covered under the plan
    "45": TriageClass.LEGITIMATE,  # charge exceeds fee schedule (write-off)
    "18": TriageClass.LEGITIMATE,  # exact duplicate claim/service
}


def classify_carc(carc_code: str) -> TriageClass:
    """Return the triage class for a CARC code (prefix-tolerant, e.g. 'CO-50')."""
    code = carc_code.strip().upper().removeprefix("CO-").removeprefix("PR-")
    code = code.removeprefix("OA-").removeprefix("PI-").lstrip("-")
    return _CARC_TO_CLASS.get(code, TriageClass.UNKNOWN)


def known_carcs() -> frozenset[str]:
    """The set of CARCs with an explicit routing (spec 0.2 coverage check)."""
    return frozenset(_CARC_TO_CLASS)
