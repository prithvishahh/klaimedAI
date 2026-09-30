"""Policy retrieval tests (spec 1.5 RAG)."""

from __future__ import annotations

from rcm.appeals.retriever import InMemoryRetriever
from rcm.policy.scraper import scrape_policies


def _retriever() -> InMemoryRetriever:
    return InMemoryRetriever(scrape_policies("dermatology") + scrape_policies("orthopedics"))


def test_retrieves_relevant_policy_first() -> None:
    top = _retriever().retrieve("skin lesion excision medical necessity D48.5", k=1)
    assert top
    assert "Skin Lesions" in top[0].title


def test_cpt_match_boosts_relevance() -> None:
    # CPT 11100 is listed in the derm lesion-removal LCD -> should rank first.
    results = _retriever().retrieve("medical necessity coverage", cpt_codes=("11100",), k=1)
    assert "11100" in results[0].cpt_codes


def test_k_limits_results() -> None:
    assert len(_retriever().retrieve("coverage", k=2)) == 2
