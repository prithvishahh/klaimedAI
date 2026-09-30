"""Appeal drafter tests (spec 1.5) — deterministic TemplateDrafter."""

from __future__ import annotations

from decimal import Decimal

from rcm.appeals.drafter import TemplateDrafter
from rcm.appeals.model import AppealContext
from rcm.appeals.retriever import InMemoryRetriever
from rcm.policy.scraper import scrape_policies
from tests.claims.factories import build_claim


def _context() -> AppealContext:
    return AppealContext(
        claim=build_claim(), carc_code="50", denied_amount=Decimal("150.00")
    )


def test_body_cites_policy_and_maps_evidence() -> None:
    ctx = _context()
    policies = InMemoryRetriever(scrape_policies("dermatology")).retrieve(
        "skin lesion D48.5", cpt_codes=("11100",), k=1
    )
    body = TemplateDrafter().draft(ctx, policies).body
    # Cites the payer's own policy by title...
    assert policies[0].title in body
    # ...maps documented chart evidence (D48.5 is in the chart)...
    assert "D48.5" in body
    # ...and explicitly requests NO code change.
    assert "No change to the billed codes" in body


def test_template_drafter_uses_no_model() -> None:
    drafted = TemplateDrafter().draft(_context(), [])
    assert drafted.model is None
    assert drafted.prompt_hash is None
