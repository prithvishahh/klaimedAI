#!/usr/bin/env python3
"""Scrape LCD/NCD coverage policies into policy_doc + embeddings (spec 0.6).

Phase 0 uses the offline seed (see rcm/policy/scraper.py). Policy text is public
(no PHI), so embedding it through any provider is fine. Requires a running DB.

Usage:  python scripts/scrape_lcd.py dermatology
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from rcm.core.db import session_scope
from rcm.models.entities import PolicyDoc
from rcm.policy.embeddings import get_embedder
from rcm.policy.scraper import available_specialties, scrape_policies


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: python scripts/scrape_lcd.py <{'|'.join(available_specialties())}>",
              file=sys.stderr)
        return 2
    specialty = sys.argv[1]
    policies = scrape_policies(specialty)
    if not policies:
        print(f"no seed policies for {specialty!r}; try: {available_specialties()}",
              file=sys.stderr)
        return 1

    embedder = get_embedder()
    written = 0
    with session_scope() as session:
        for p in policies:
            exists = session.scalars(
                select(PolicyDoc).where(PolicyDoc.title == p.title)
            ).first()
            if exists is not None:
                continue
            session.add(
                PolicyDoc(
                    doc_type=p.doc_type,
                    title=p.title,
                    text=p.text,
                    cpt_codes=list(p.cpt_codes),
                    url=p.url,
                    effective_date=p.effective_date,
                    embedding=embedder.embed(p.text),
                )
            )
            written += 1
    print(f"wrote {written} policy doc(s) for {specialty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
