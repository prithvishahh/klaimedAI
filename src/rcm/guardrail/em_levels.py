"""Evaluation & Management (E/M) code levels.

The guardrail must treat an E/M level increase (e.g. 99213 -> 99214) as
upcoding. This maps E/M CPT codes to an ordinal level so the guardrail can
compare "before" and "after" severity. Non-E/M codes map to 0 (not applicable).

Covers the office/outpatient families that dominate ambulatory practices
(the spec's beachhead: derm, ortho, GI, rheum, sleep, behavioral health).
"""

from __future__ import annotations

# CPT code -> ordinal E/M level. Higher = higher reimbursement.
_EM_LEVELS: dict[str, int] = {
    # Office/outpatient, new patient
    "99201": 1,
    "99202": 2,
    "99203": 3,
    "99204": 4,
    "99205": 5,
    # Office/outpatient, established patient
    "99211": 1,
    "99212": 2,
    "99213": 3,
    "99214": 4,
    "99215": 5,
    # Office/outpatient consultations
    "99241": 1,
    "99242": 2,
    "99243": 3,
    "99244": 4,
    "99245": 5,
}


def em_level(cpt_code: str) -> int:
    """Return the ordinal E/M level for ``cpt_code``, or 0 if it is not E/M."""
    return _EM_LEVELS.get(cpt_code.strip(), 0)


def is_em_code(cpt_code: str) -> bool:
    """True if ``cpt_code`` is a recognized E/M code."""
    return cpt_code.strip() in _EM_LEVELS
