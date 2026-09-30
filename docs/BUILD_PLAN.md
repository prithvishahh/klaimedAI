# Medical RCM — Phase 0 (Read-Only) + Compliance Guardrail

## Context

We're building an AI-native medical Revenue Cycle Management (RCM) system from the
spec in `medical_rcm_build_spec.pdf`. The business: take over a physician
practice's denied-claim backlog on contingency, recover money with agents behind a
**hard-coded compliance guardrail that architecturally cannot upcode**, and use the
outcomes to build a payer-specific appeal win-rate table.

The single largest company risk (spec §7) is an AI that learns to add modifiers /
bump E&M levels to get claims paid — that is the **False Claims Act** (treble
damages, federal, criminal). The whole product only survives if the guardrail is
**code, not a prompt**, unit-tested with adversarial cases, and unbypassable — and
if PHI is handled to HIPAA standard **from line one**. The user's explicit
requirement: security-compliant from the get-go, prod-ready, not vibecoded.

This plan delivers the **security-first slice**: the production repo skeleton with
HIPAA controls baked in, the Guardrail (spec §7) with an adversarial test suite as
a CI gate, and the Phase 0 read-only pipeline (spec §8): X12 835 parser →
denial rows, CARC/RARC taxonomy → triage routing, timely-filing deadline
calculator, TRIAGE agent v0, LCD/NCD policy scraper + embeddings, append-only
audit log. **Zero writes, zero outbound claims, zero real PHI** — synthetic 835s
only. This proves the technical thesis (spec §10 kill criterion: TRIAGE ≥90%
agreement with a human coder) without touching the write path.

Scope: **Phase 0 + Guardrail · synthetic test data · Docker Compose local**.
AWS HIPAA infra (KMS/BAA/VPC) is documented as a later step, not built now.

## Stack (per spec §9)

- **Python 3.12 + FastAPI** (best EDI/healthcare ecosystem)
- **Postgres 16 + pgvector** via Docker Compose (policy embeddings next to relational data)
- **SQLAlchemy 2.0 + Alembic** migrations
- **pydantic-settings** for config/secrets (never hardcoded)
- **structlog** with a PHI-redaction processor
- **cryptography** (AES-256-GCM) for application-level PHI field encryption
- **Anthropic SDK** — CARC classification on `claude-haiku-4-5` (cheap, high-volume);
  reasoning/drafting later on `claude-opus-4-8` with adaptive thinking. Phase 0
  triage is **mostly deterministic** (taxonomy table); the model is only a
  tie-breaker for ambiguous CARCs, and **PHI is de-identified before any model call**.
- Dev tooling: `ruff`, `mypy`, `pytest`, `bandit` (SAST), `pip-audit` (deps),
  `gitleaks` (secret scan), `pre-commit`.

## Security & compliance controls (baked in from line one)

These are the non-negotiables. Each is a concrete module, not a doc promise.

1. **PHI encryption at rest** — `rcm/core/crypto.py`: AES-256-GCM envelope
   encryption (random nonce per value, ciphertext + nonce stored together). Master
   key from env (`RCM_MASTER_KEY`) in dev; documented KMS-backed data key for prod.
   A SQLAlchemy `EncryptedString` TypeDecorator transparently encrypts the `_enc`
   columns (`patient.dob_enc`, `patient.name_enc`, `encounter.chart_text_enc`).
   Fail-closed: no key → refuse to start.
2. **No PHI in logs** — `rcm/core/logging.py`: structlog processor that drops/masks
   known PHI fields (name, dob, mrn, ssn, chart_text) and never serializes raw
   chart text or model prompt bodies. Audit log stores `prompt_hash`, not the prompt.
3. **Append-only audit log** — Alembic migration adds a Postgres trigger that
   raises on UPDATE/DELETE of `audit_log`; the app DB role is granted INSERT/SELECT
   only. Every agent action, prompt hash, model, before/after (encrypted) is appended.
4. **De-identification before model calls** — `rcm/llm/deident.py` strips/tokenizes
   PHI; `rcm/llm/client.py` fail-closes if residual PHI patterns are detected before
   sending. Policy docs (LCD/NCD) are public — no PHI — so embedding them is safe.
5. **The Guardrail** — pure, deterministic, no I/O, unit-tested; the adversarial
   suite is a **CI gate** (spec §1.1: "ship nothing until this passes"). No outbound
   path exists in Phase 0, but building + proving it now is the security-first move.
6. **Least privilege** — separate Postgres roles for migrations vs. app runtime;
   `.env` gitignored, only `.env.example` committed; secrets via pydantic-settings.
7. **Timely-filing deadline** as a first-class **indexed** object with a report of
   at-risk denials (T-30/T-14/T-7); full alerting is Phase 1 (spec risk table).
8. **CI supply-chain hygiene** — `bandit`, `pip-audit`, `gitleaks`, `ruff`, `mypy`,
   `pytest` all gate merges. `SECURITY.md` (threat model + PHI handling) and
   `COMPLIANCE.md` (HIPAA control mapping, BAA/CPC/E&O prerequisites from spec §9).

## Repo layout

```
medical-rcm/
  README.md  SECURITY.md  COMPLIANCE.md
  pyproject.toml  .env.example  .gitignore  .pre-commit-config.yaml
  docker-compose.yml                      # postgres+pgvector
  .github/workflows/ci.yml                # lint, type, test, bandit, pip-audit, gitleaks
  alembic/  alembic.ini                   # migrations incl. audit-log append-only trigger
  src/rcm/
    core/     config.py  crypto.py  logging.py  db.py
    models/   *.py                         # SQLAlchemy models = data model below
    guardrail/ guardrail.py  em_levels.py  icd_chart.py    # ★ spec §7
    edi/      x12_835.py  segments.py       # CLP/SVC/CAS → denial rows
    taxonomy/ carc.py  loader.py            # CARC/RARC → triage_class
    deadlines/ calculator.py               # per-payer filing/appeal windows
    triage/   agent.py  scoring.py          # TRIAGE v0: $ × p(win)
    policy/   scraper.py  embeddings.py     # LCD/NCD → policy_doc + pgvector
    audit/    log.py                        # append-only writer
    llm/      client.py  deident.py         # Claude wrapper, PHI de-id (fail-closed)
    api/      app.py  routes.py             # FastAPI: read-only status/queue endpoints
  tests/
    guardrail/test_adversarial.py          # ★ THE CI gate — must be 100% green
    edi/test_835_parser.py  taxonomy/  deadlines/  triage/  crypto/
  data/samples/                            # synthetic 835s (fake PHI) — real data gitignored
  scripts/  seed_carc.py  scrape_lcd.py  gen_synthetic_835.py
```

## Data model (Postgres, spec §6 — PHI columns encrypted at rest)

Implement as SQLAlchemy models exactly per spec §6:
`practice, provider, patient, payer, encounter, claim, claim_line, denial,
appeal, auth_request, policy_doc(embedding vector(1536)), appeal_outcome`
(the moat table, UNIQUE(payer_id, carc_code, specialty, strategy)),
`audit_log` (APPEND ONLY), `guardrail_block`.

For Phase 0 the write-path tables (`appeal`, `auth_request`) are created but
unused. `denial.appeal_deadline`, `denial.priority`, and `appeal_outcome`'s unique
key are **indexed**. Embedding dim is **configurable** (spec shows 1536); Phase 0
policy docs are public, so any embedding provider is fine — default to a local/open
model to avoid a second vendor BAA. Never embed chart/PHI via a non-BAA service.

## The Guardrail (spec §7 — the load-bearing component)

`guardrail(original: Claim, proposed: Claim) -> Verdict` as a **pure function**,
implementing all 6 rules verbatim:
1. CPT set changed → BLOCK → human coder
2. Modifier set changed (additions especially — the classic upcoding vector) → BLOCK
3. ICD added but not supported by chart text (`icd_supported_by_chart`) → BLOCK
4. Units increased → BLOCK
5. Charge increased → BLOCK
6. E&M level raised (99213→99214, via `em_levels.py` ordering) → BLOCK
Otherwise ALLOW. Allowed without review: demographic corrections, attaching
docs already in chart, payer-ID/routing fixes, identical resubmit, appeal *letter*
drafting, citing payer policy.

`tests/guardrail/test_adversarial.py` encodes the spec §1.1 attacks — agent tries
to add `-25`, bump E&M, invent an ICD, raise units/charge — and asserts 100% BLOCK.
CI fails the build if any adversarial case passes. This is the gate everything else
sits behind.

## Phase 0 tickets (spec §8) — Definition of Done

| # | Ticket | Done when |
|---|---|---|
|0.1| X12 835 parser (CLP/SVC/CAS → denial rows) | Parses the synthetic 835 corpus with zero errors |
|0.2| CARC/RARC reference tables → triage_class | All CARCs in corpus mapped to the §5 taxonomy |
|0.4| Timely-filing deadline calculator (per-payer windows) | Every denial has a computed, indexed `appeal_deadline` |
|0.5| TRIAGE agent v0 (fixable/appealable/legitimate, rank by $×p(win)) | ≥90% agreement vs. labeled synthetic set |
|0.6| LCD/NCD scraper → policy_doc + embeddings | Beachhead-specialty coverage policy is searchable via pgvector |
|0.7| Append-only audit log | Cannot be written except by append (trigger + role enforced) |
|G  | Guardrail + adversarial suite | 100% of adversarial tests BLOCK; CI gate green |

(0.3 real PM-system integration is deferred — needs a BAA and a live customer, per
spec risk table "Start with ONE." We stand up the read-only ingest against
synthetic files instead.)

## Verification (end-to-end, local)

1. `docker compose up -d` → Postgres+pgvector healthy; `alembic upgrade head`
   creates schema + audit-log append-only trigger.
2. `python scripts/gen_synthetic_835.py` → fake-PHI 835 files in `data/samples/`.
3. `pytest` — all green; **`tests/guardrail/test_adversarial.py` at 100%** is the
   hard gate. Include a crypto round-trip test and an "audit log rejects UPDATE/
   DELETE" test.
4. `python -m rcm.edi.x12_835 data/samples/*.835` → denial rows written; verify
   `denial.appeal_deadline` and `priority` populated and indexed.
5. Run TRIAGE v0 over the labeled synthetic set → print agreement %; assert ≥90%.
6. `python scripts/scrape_lcd.py <specialty>` → policy_doc rows + embeddings;
   a pgvector similarity query returns the relevant coverage policy.
7. `uvicorn rcm.api.app:app` → read-only status/queue endpoints respond; confirm
   **no PHI in logs** (grep structlog output) and **no outbound claim path exists**.
8. CI (`.github/workflows/ci.yml`): ruff + mypy + pytest + bandit + pip-audit +
   gitleaks all pass on the first commit.

## Explicitly out of scope this pass
Write path / 837P generator / clearinghouse (Phase 1); appeal drafting agent
(Phase 1); prior-auth RPA (Phase 2); AWS HIPAA IaC (documented, not built);
real PM-system integration and real PHI (needs BAA + customer). `/remote-control`
cannot be enabled from within a session.
