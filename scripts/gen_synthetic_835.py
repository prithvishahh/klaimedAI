#!/usr/bin/env python3
"""Generate synthetic X12 835 remittances with FAKE PHI for dev and tests.

No real patient data ever enters this repo. These files exercise the parser and
triage across the full denial taxonomy (spec §5): administrative, eligibility,
authorization, medical-necessity, bundling, and legitimate denials.

Writes ``data/samples/*.sample.835`` (the ``.sample.835`` suffix is the only
835 extension git will track).

Usage:  python scripts/gen_synthetic_835.py [--count N] [--seed S]
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"

# Obviously-fake PHI.
FAKE_NAMES = [
    ("DOE", "JANE"), ("SMITH", "JOHN"), ("GARCIA", "MARIA"), ("CHEN", "WEI"),
    ("PATEL", "AMIT"), ("NGUYEN", "LINH"), ("BROWN", "SAM"), ("KIM", "SOO"),
]

PAYERS = [
    ("AETNA", "60054"),
    ("UNITEDHEALTHCARE", "87726"),
    ("CIGNA", "62308"),
    ("BCBS OF TEXAS", "84980"),
]

# (CPT, [modifiers], charge) — dermatology/derm-ortho flavored.
PROCEDURES = [
    ("99213", [], "120.00"),
    ("99214", [], "180.00"),
    ("11100", [], "150.00"),  # skin biopsy
    ("17000", [], "95.00"),  # destruction premalignant lesion
    ("20610", [], "210.00"),  # arthrocentesis, major joint
    ("96372", [], "45.00"),  # therapeutic injection
]

# CARC -> (group_code, share of denial). A spread across the taxonomy.
DENIAL_SCENARIOS = [
    ("16", "CO"),   # admin: missing info
    ("11", "CO"),   # admin: dx/proc mismatch
    ("140", "CO"),  # admin: patient/insured ID
    ("27", "CO"),   # eligibility: coverage terminated
    ("31", "CO"),   # eligibility: patient not identified
    ("197", "CO"),  # authorization: no precert
    ("50", "CO"),   # medical necessity
    ("167", "CO"),  # medical necessity
    ("97", "CO"),   # bundling
    ("234", "CO"),  # bundling
    ("204", "PR"),  # legitimate: not covered / patient responsibility
    ("96", "CO"),   # legitimate: non-covered
]


def _clp_block(rng: random.Random, idx: int) -> str:
    last, first = rng.choice(FAKE_NAMES)
    cpt, mods, charge = rng.choice(PROCEDURES)
    carc, group = rng.choice(DENIAL_SCENARIOS)
    charge_d = float(charge)
    # Denied claims: paid 0, whole charge adjusted under the CARC.
    pcn = f"PCN{idx:05d}"
    payer_ccn = f"{rng.randint(10**9, 10**10 - 1)}"
    member_id = f"{rng.randint(10**8, 10**9 - 1)}"
    svc_composite = ":".join(["HC", cpt, *mods])
    pat_resp = charge if group == "PR" else "0"

    lines = [
        f"CLP*{pcn}*22*{charge}*0*{pat_resp}*12*{payer_ccn}*11",
        f"NM1*QC*1*{last}*{first}****MI*{member_id}",
        f"SVC*{svc_composite}*{charge}*0**{1}",
        "DTM*472*20260115",
        f"CAS*{group}*{carc}*{charge}",
    ]
    _ = charge_d  # (kept for readability of intent)
    return "~".join(lines)


def build_835(rng: random.Random, n_claims: int) -> str:
    payer_name, payer_id = rng.choice(PAYERS)
    header = [
        "ISA*00*          *00*          *ZZ*SENDER         "
        "*ZZ*RECEIVER       *260115*1200*^*00501*000000001*0*P*:",
        "GS*HP*SENDER*RECEIVER*20260115*1200*1*X*005010X221A1",
        "ST*835*0001",
        "BPR*I*0*C*NON************20260115",
        "TRN*1*0000000001*1234567890",
        f"N1*PR*{payer_name}",
        f"REF*2U*{payer_id}",
        "N1*PE*BEACHHEAD DERMATOLOGY*XX*1234567890",
        "LX*1",
    ]
    body = [_clp_block(rng, i) for i in range(1, n_claims + 1)]
    trailer = ["SE*99*0001", "GE*1*1", "IEA*1*000000001"]
    return "~".join([*header, *body, *trailer]) + "~"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=5, help="number of 835 files")
    ap.add_argument("--claims", type=int, default=8, help="claims per file")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    written = 0
    for i in range(1, args.count + 1):
        path = SAMPLES_DIR / f"remit_{i:03d}.sample.835"
        path.write_text(build_835(rng, args.claims), encoding="utf-8")
        written += 1
        print(f"wrote {path}  ({args.claims} claims)")
    print(f"\n{written} synthetic 835 file(s) in {SAMPLES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
