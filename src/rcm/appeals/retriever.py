"""Policy retrieval for appeals (RAG over the policy index, spec 1.5).

Retrieves the payer's own coverage criteria (LCD/NCD/commercial policy) so the
appeal can cite them verbatim. Policy text is PUBLIC — no PHI — so this side of
the appeal never touches the de-identification boundary.

Two implementations behind one Protocol:
  * ``PgVectorRetriever`` — production; nearest-neighbour over ``policy_doc``.
  * ``InMemoryRetriever`` — offline/tests; ranks a supplied policy set with the
    same embedder + cosine similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from rcm.appeals.model import RetrievedPolicy
from rcm.policy.embeddings import Embedder, cosine_similarity, get_embedder
from rcm.policy.scraper import PolicyDocData

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class PolicyRetriever(Protocol):
    def retrieve(
        self, query: str, *, cpt_codes: tuple[str, ...] = (), k: int = 3
    ) -> list[RetrievedPolicy]:
        ...


# A small boost for policies that explicitly list one of the claim's CPT codes.
_CPT_MATCH_BOOST = 0.1


class InMemoryRetriever:
    """Ranks a fixed set of policies (e.g. the offline seed) by cosine similarity."""

    def __init__(
        self, policies: list[PolicyDocData], embedder: Embedder | None = None
    ) -> None:
        self._embedder = embedder or get_embedder()
        self._policies = policies
        self._vectors = [self._embedder.embed(p.text) for p in policies]

    def retrieve(
        self, query: str, *, cpt_codes: tuple[str, ...] = (), k: int = 3
    ) -> list[RetrievedPolicy]:
        qv = self._embedder.embed(query)
        scored: list[RetrievedPolicy] = []
        for policy, vec in zip(self._policies, self._vectors, strict=True):
            score = cosine_similarity(qv, vec)
            if cpt_codes and set(cpt_codes) & set(policy.cpt_codes):
                score += _CPT_MATCH_BOOST
            scored.append(
                RetrievedPolicy(
                    title=policy.title,
                    text=policy.text,
                    url=policy.url,
                    score=score,
                    cpt_codes=policy.cpt_codes,
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]


class PgVectorRetriever:
    """Nearest-neighbour retrieval over ``policy_doc`` using pgvector."""

    def __init__(self, session: Session, embedder: Embedder | None = None) -> None:
        self._session = session
        self._embedder = embedder or get_embedder()

    def retrieve(
        self, query: str, *, cpt_codes: tuple[str, ...] = (), k: int = 3
    ) -> list[RetrievedPolicy]:
        from sqlalchemy import text

        qv = self._embedder.embed(query)
        rows = self._session.execute(
            text(
                "SELECT title, text, url, cpt_codes, "
                "       1 - (embedding <=> CAST(:v AS vector)) AS score "
                "FROM policy_doc "
                "WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"
            ),
            {"v": str(qv), "k": k},
        ).all()
        return [
            RetrievedPolicy(
                title=r.title,
                text=r.text,
                url=r.url,
                score=float(r.score),
                cpt_codes=tuple(r.cpt_codes or ()),
            )
            for r in rows
        ]
