"""Policy embeddings + retrieval sanity (spec 0.6, offline)."""

from __future__ import annotations

from rcm.policy.embeddings import Embedder, cosine_similarity
from rcm.policy.scraper import available_specialties, scrape_policies


def test_embedding_dimension_matches_config() -> None:
    emb = Embedder()
    assert len(emb.embed("skin lesion excision")) == emb.dim


def test_identical_text_is_maximally_similar() -> None:
    emb = Embedder()
    v = emb.embed("actinic keratosis destruction")
    assert cosine_similarity(v, v) > 0.999


def test_lexical_overlap_beats_unrelated() -> None:
    emb = Embedder()
    q = emb.embed("skin lesion excision medically necessary")
    related = emb.embed("excision of a skin lesion is medically necessary when symptomatic")
    unrelated = emb.embed("major joint injection arthrocentesis ultrasound guidance")
    assert cosine_similarity(q, related) > cosine_similarity(q, unrelated)


def test_retrieval_finds_the_right_policy() -> None:
    """A dermatology query should rank the derm LCD above the ortho LCD."""
    emb = Embedder()
    policies = scrape_policies("dermatology") + scrape_policies("orthopedics")
    query = emb.embed("destruction of actinic keratosis lesions on the skin")
    ranked = sorted(
        policies,
        key=lambda p: cosine_similarity(query, emb.embed(p.text)),
        reverse=True,
    )
    assert "Actinic Keratosis" in ranked[0].title


def test_seed_specialties_present() -> None:
    assert "dermatology" in available_specialties()
