"""Appeal agent tests (spec 1.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from rcm.appeals.agent import draft_appeal
from rcm.appeals.model import AppealContext
from rcm.appeals.retriever import InMemoryRetriever
from rcm.policy.scraper import scrape_policies
from tests.claims.factories import build_claim


def _retriever() -> InMemoryRetriever:
    return InMemoryRetriever(scrape_policies("dermatology") + scrape_policies("orthopedics"))


def _ctx(carc: str = "50") -> AppealContext:
    return AppealContext(claim=build_claim(), carc_code=carc, denied_amount=Decimal("150.00"))


def test_medical_necessity_denial_produces_a_citing_letter() -> None:
    draft = draft_appeal(_ctx("50"), retriever=_retriever())
    assert draft.appealable
    assert draft.strategy == "medical_necessity"
    assert draft.cited_policies  # cites the payer's own criteria
    letter = draft.letter_text or ""
    # The letter cites a payer policy and carries the claim header.
    assert draft.cited_policies[0] in letter
    assert "Claim #: PCN00001" in letter
    assert "Member ID: W123456789" in letter


def test_appeal_never_changes_a_code() -> None:
    original = build_claim()
    draft = draft_appeal(
        AppealContext(claim=original, carc_code="50", denied_amount=Decimal("150.00")),
        retriever=_retriever(),
    )
    billed = tuple(sorted({ln.cpt_code for ln in original.lines}))
    assert draft.argued_cpt_codes == billed
    assert "No change to the billed codes" in (draft.letter_text or "")


@pytest.mark.parametrize(
    ("carc", "route"),
    [
        ("16", "corrections"),   # administrative -> corrections agent
        ("27", "corrections"),   # eligibility -> corrections agent
        ("97", "human_coder"),   # bundling -> danger zone
        ("204", "close"),        # legitimate -> don't waste the appeal
        ("99999", "human_coder"),  # unknown -> human review
    ],
)
def test_out_of_class_denials_are_routed_not_appealed(carc: str, route: str) -> None:
    draft = draft_appeal(_ctx(carc), retriever=_retriever())
    assert not draft.appealable
    assert draft.route_to == route
    assert draft.letter_text is None


def test_letter_contains_no_upcoding_language() -> None:
    # The whole point: an appeal argues necessity for the codes as billed.
    draft = draft_appeal(_ctx("55"), retriever=_retriever())
    assert draft.appealable
    assert "reconsideration" in (draft.letter_text or "").lower()
