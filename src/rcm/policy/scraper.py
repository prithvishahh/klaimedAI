"""LCD/NCD coverage-policy ingestion (spec 0.6).

Medicare's Local/National Coverage Determinations are free, public, and
structured — the appeal agent's ammunition ("cite the payer's own criteria back
at them"). This module produces :class:`PolicyDocData` records and, given a DB
session, upserts them into ``policy_doc`` with embeddings.

Phase 0 ships a small **offline seed** of realistic policy stubs for the
beachhead specialties, so the pipeline (scrape → embed → search) runs with no
network. The live Medicare Coverage Database path is documented behind
``fetch_live`` — swap it in when a network egress + refresh cadence is set up.
Policy text is PUBLIC (no PHI), so embedding it through any provider is fine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class PolicyDocData:
    doc_type: str  # LCD | NCD | commercial_policy
    title: str
    text: str
    cpt_codes: tuple[str, ...] = ()
    url: str | None = None
    effective_date: date | None = None


# Offline seed — realistic structure, illustrative coverage language.
_SEED: dict[str, list[PolicyDocData]] = {
    "dermatology": [
        PolicyDocData(
            doc_type="LCD",
            title="Removal of Benign and Malignant Skin Lesions (L34200)",
            cpt_codes=("11400", "11401", "11402", "11100", "17000"),
            effective_date=date(2025, 1, 1),
            url="https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=34200",
            text=(
                "Excision or destruction of a skin lesion is considered medically "
                "necessary when the lesion is symptomatic (bleeding, pruritus, pain), "
                "shows signs of malignancy, or has documented change in size, color, "
                "or morphology. Photographic documentation and a diagnosis code "
                "supporting medical necessity (e.g. C44.- for skin malignancy, D48.5 "
                "for uncertain behavior) must be present in the record. Removal solely "
                "for cosmetic purposes is not covered."
            ),
        ),
        PolicyDocData(
            doc_type="LCD",
            title="Actinic Keratosis Destruction (L35498)",
            cpt_codes=("17000", "17003", "17004"),
            effective_date=date(2025, 1, 1),
            url="https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=35498",
            text=(
                "Destruction of actinic keratoses (ICD-10 L57.0) is covered when the "
                "lesions are clinically documented. The number of lesions treated must "
                "be supported in the chart. Field therapy without documented lesion "
                "count may be denied for insufficient documentation."
            ),
        ),
    ],
    "orthopedics": [
        PolicyDocData(
            doc_type="LCD",
            title="Major Joint Injection/Aspiration (L33622)",
            cpt_codes=("20610", "20611"),
            effective_date=date(2025, 1, 1),
            url="https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33622",
            text=(
                "Arthrocentesis or injection of a major joint (CPT 20610/20611) is "
                "covered for documented osteoarthritis (M17.-, M19.-) or inflammatory "
                "arthropathy when conservative therapy has been tried. Ultrasound "
                "guidance (20611) requires a permanently recorded image in the chart."
            ),
        ),
    ],
}


def scrape_policies(specialty: str) -> list[PolicyDocData]:
    """Return coverage policies for a specialty (offline seed in Phase 0)."""
    return list(_SEED.get(specialty.strip().lower(), []))


def available_specialties() -> list[str]:
    return sorted(_SEED)


def fetch_live(specialty: str) -> list[PolicyDocData]:  # pragma: no cover
    """Live Medicare Coverage Database fetch (not enabled in Phase 0).

    Wire this to the MCD (https://www.cms.gov/medicare-coverage-database) with an
    httpx client once network egress and a refresh cadence are approved. The
    return contract is identical to :func:`scrape_policies`.
    """
    raise NotImplementedError(
        "live MCD scraping is not enabled in Phase 0; use scrape_policies() (seed)"
    )
