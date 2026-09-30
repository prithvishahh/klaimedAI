"""Domain enums shared across models, taxonomy, and triage."""

from __future__ import annotations

from enum import Enum


class TriageClass(str, Enum):
    """Denial routing classes (spec §5 denial taxonomy)."""

    ADMINISTRATIVE = "administrative"  # CO-16, CO-11, CO-140 — fix data + resubmit
    ELIGIBILITY = "eligibility"  # CO-27, CO-31 — re-verify / rebill
    AUTHORIZATION = "authorization"  # CO-197 — retro-auth
    MEDICAL_NECESSITY = "medical_necessity"  # CO-50/55/167 — appeal w/ policy + chart
    BUNDLING = "bundling"  # CO-97/234/236 — DANGER ZONE, human coder ALWAYS
    LEGITIMATE = "legitimate"  # PR-204, CO-96, duplicate — close, don't appeal
    UNKNOWN = "unknown"  # unmapped CARC — needs review


# Recoverability is highest for administrative fixes, zero for legitimate denials.
# Bundling routes to a human coder, so its automated recoverability is 0 here.
RECOVERABILITY: dict[TriageClass, float] = {
    TriageClass.ADMINISTRATIVE: 0.85,
    TriageClass.ELIGIBILITY: 0.55,
    TriageClass.AUTHORIZATION: 0.50,
    TriageClass.MEDICAL_NECESSITY: 0.40,
    TriageClass.BUNDLING: 0.0,
    TriageClass.LEGITIMATE: 0.0,
    TriageClass.UNKNOWN: 0.10,
}


class GroupCode(str, Enum):
    """X12 CAS group codes. CO is where recoverable money hides."""

    CO = "CO"  # contractual obligation (write-off)
    PR = "PR"  # patient responsibility
    OA = "OA"  # other adjustment
    PI = "PI"  # payer initiated


class AppealOutcome(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    DENIED = "denied"
    PARTIAL = "partial"


class AppealStrategy(str, Enum):
    MEDICAL_NECESSITY = "medical_necessity"
    CORRECTED_CLAIM = "corrected_claim"
    RETRO_AUTH = "retro_auth"
    ELIGIBILITY_REBILL = "eligibility_rebill"


class SubmissionChannel(str, Enum):
    PORTAL = "portal"
    FAX = "fax"
    X12_278 = "x12_278"


class PolicyDocType(str, Enum):
    LCD = "LCD"
    NCD = "NCD"
    COMMERCIAL_POLICY = "commercial_policy"
