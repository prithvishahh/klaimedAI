# Medical RCM — Project Status & Handoff

_A self-contained status report for planning the next steps. Covers what's built,
how capable each piece is, and what remains from the original build spec._

Last updated after commit `4579699` (Phase 1.5). **107 tests pass**; ruff / mypy
(strict) / bandit all clean.

---

## 1. What the product is

An AI-native medical **Revenue Cycle Management** system. The wedge: take a
physician practice's **denied-claim backlog**, recover the money with agents —
behind a hard-coded compliance guardrail that **architecturally cannot upcode** —
then use the outcomes to build a payer-specific appeal win-rate table nobody else
has. Beachhead: 5–25 provider specialty practices (dermatology first).

**Everything today runs on synthetic data (fake PHI). No external system is
live** — no real practice/EHR, no real clearinghouse, no real payer portal, no
real Claude calls in the tested paths. The engineering is real and production-
structured; the _integrations and data_ are simulated.

---

## 2. Tech stack (as built)

- **Python 3.12 + FastAPI**, SQLAlchemy 2.0 + Alembic
- **PostgreSQL + pgvector** (policy embeddings next to relational data)
- **Anthropic Claude** clients wired (Haiku for CARC classify, Opus for drafting) —
  present but **not exercised** without an API key; deterministic fallbacks are the
  default and the tested path
- Dev/CI: ruff, mypy (strict), bandit (SAST), pip-audit, gitleaks, pytest
- Local dev: Docker Compose (PG16) **or** Homebrew Postgres 17 on `:5433` (this
  machine has no Docker; a system PG12 owns `:5432`). Helper: `scripts/dev_db.sh`.

---

## 3. Capability ratings (legend)

| Rating | Meaning |
|---|---|
| 🟢 **Solid** | Production-grade logic, well-tested. Would work as-is on real inputs of this shape. |
| 🟡 **Functional (synthetic)** | Works end-to-end but only against synthetic data / simplified formats; needs hardening for real-world variance. |
| 🟠 **Prototype/offline** | Works, but a key dependency is stubbed/simulated (e.g. real integration, real model, real data). |
| ⚪ **Stub/documented** | Interface + docs exist; implementation deferred. |
| 🔴 **Not started** | — |

---

## 4. What's implemented (by spec ticket)

### Phase 0 — read-only ingest + triage

| # | Ticket | Status | Capability & notes |
|---|---|---|---|
| 0.1 | X12 835 parser → denial rows | 🟡 | Parses CLP/SVC/CAS, flattens to denial rows. Verified on synthetic 835s (0 errors, 40 rows). **Not hardened** against real-payer 835 dialects/edge segments. |
| 0.2 | CARC/RARC → triage_class | 🟡 | ~25 CARCs curated across all 6 taxonomy families. **Not the full ~400 CARC set** — unmapped codes safely route to `UNKNOWN`/human. |
| 0.3 | Read-only PM/EHR integration (Athena/DrChrono) | 🔴 | Deferred — needs a BAA + real API + a paying practice. Ingest runs from synthetic 835 files instead. |
| 0.4 | Timely-filing deadline calculator | 🟢 | Per-payer filing/appeal windows; `appeal_deadline` computed + **indexed**; T-30/14/7 risk buckets. **No push alerting/notifications** yet (API exposes at-risk list). |
| 0.5 | TRIAGE agent v0 | 🟢 | Deterministic taxonomy routing + rank by `$ × p(win)`. **≥90% agreement** vs a hand-labeled golden set (spec kill criterion met). LLM tie-break wired but unused. p(win) is a per-class prior until the moat table has data. |
| 0.6 | LCD/NCD scraper → policy index | 🟠 | Offline **seed** policies (derm/ortho) embedded into pgvector; retrieval works. **Live Medicare Coverage Database scraping is stubbed** (`fetch_live`). Embeddings use an **offline hash provider**, not a real semantic model. |
| 0.7 | Append-only audit log | 🟢 | Postgres trigger **and** least-privilege grants (app role denied UPDATE/DELETE). Verified against real PG. |

### Phase 1 — the write path (first revenue)

| # | Ticket | Status | Capability & notes |
|---|---|---|---|
| 1.1 | **Compliance guardrail** + adversarial suite | 🟢🟢 | The strongest piece. Pure, deterministic 6-rule block on any CPT/modifier/ICD/units/charge/E&M change that could raise reimbursement. **Adversarial suite is a CI gate — 100% of upcoding vectors blocked.** Every outbound artifact passes it. |
| 1.2 | Corrections agent (easy class) | 🟢 | Data-only fixes: member ID, demographics, payer rebill (CO-16/140/27/31). **Copies service lines verbatim — cannot touch a code.** Refuses out-of-class denials. |
| 1.3 | 837P generator + validator | 🟡 | Emits well-formed 837P (envelope, provider under own NPI+EIN, CLM/HI/SV1, correct SE counts) + a self-validator. **Not yet validated against a real clearinghouse's edit rules.** |
| 1.4 | Clearinghouse integration | 🟠 | 277CA build/parse (front-end accept/reject, distinct from an 835 denial) + a `Clearinghouse` Protocol + a **simulated** clearinghouse that closes the loop (submit → 277CA → paid 835). **No real Availity/Office Ally adapter**; 277CA parse is a matched pair, not real-payer-hardened. |
| 1.5 | Appeal agent (medical necessity) | 🟡 | RAG over the policy index → letter citing the payer's **own** LCD criteria + chart evidence. Guardrail-safe: produces a **letter, never a claim change**; PHI de-identified before any model call. **`TemplateDrafter` (deterministic) is the tested path; `ClaudeDrafter` (Opus) needs an API key and isn't exercised.** Quality vs the spec's "coder approves ≥70% unedited" is **unmeasured** (no human-review loop yet). |
| 1.6 | Human review console (queue, diff, approve/edit, submit) | 🔴 | Not started. This is the human-in-the-loop UI the whole Phase-1 model depends on. |
| 1.7 | Outcome ingestion (835 back → `appeal.outcome`, `recovered_amount`) | 🔴 | Not started. Closes the learning loop; writes the first `appeal_outcome` row. |
| 1.8 | Contingency billing (track recovered $, invoice 25%) | 🔴 | Not started. |

### Phase 2 — the moat & prior auth

| # | Ticket | Status |
|---|---|---|
| 2.1 | Populate `appeal_outcome`, feed win rates into triage/appeal | 🔴 (schema exists) |
| 2.2 | Commercial payer policy ingestion (Aetna/UHC/Cigna/BCBS PDFs) | 🔴 (only Medicare seed) |
| 2.3 | PRIOR-AUTH agent (portal RPA + fax fallback) | 🔴 |
| 2.4 | Reduce human review 100% → exceptions | 🔴 |
| 2.5 | Practice-facing dashboard | 🔴 |

### Phase 3 — full RCM

Front-end eligibility verification, charge capture, patient collections. 🔴 Not
started (spec says only after Phase 2 margins are proven).

---

## 5. Cross-cutting: security, compliance, infra

| Area | Status | Notes |
|---|---|---|
| PHI encryption at rest (AES-256-GCM) | 🟢 | Transparent `EncryptedString` columns; fail-closed on missing key; verified ciphertext-at-rest in PG. |
| No PHI in logs | 🟢 | structlog redaction; prompt bodies never logged (hash only). |
| De-identification before model calls | 🟢 | Fail-closed (`assert_deidentified`); tested. |
| Append-only audit log | 🟢 | Trigger + least-privilege roles. |
| Secret scanning / SAST / dep audit in CI | 🟢 | gitleaks, bandit, pip-audit, ruff, mypy, pytest. |
| API authN/authZ (RBAC) | 🔴 | Read-only endpoints have **no auth** yet. |
| Long-running workflow engine (Temporal/Inngest per spec) | 🔴 | Not integrated; flows are synchronous. Appeals are multi-day/retry-heavy — this is a real gap for production. |
| Real embeddings model | 🟠 | Offline hash embedder; swap to a real semantic model (Voyage/sentence-transformers) for quality. |
| Live Claude calls | 🟠 | Clients wired; not run (no key in tested paths). |
| AWS HIPAA hosting (BAA, KMS, VPC, RDS) | ⚪ | Documented in `COMPLIANCE.md`; **no IaC built**. Local dev only. |
| SOC 2 / HIPAA attestation | 🔴 | Technical controls in code; not audited. |

### Legal / business prerequisites (spec §9 — process, not code, all outstanding)
- [ ] **BAA** with every practice + every subprocessor (model/hosting) — blocker for real PHI
- [ ] Healthcare attorney engaged before first contract
- [ ] E&O + cyber-liability insurance bound
- [ ] Certified coder (CPC) on staff/contract — the fraud firewall / reviewer for 1.6
- [ ] Contract language (commercially reasonable efforts, liability capped, NPI attestation)

---

## 6. What the product can actually do today (end to end, synthetic)

Runnable now (`python scripts/demo_837p.py` shows 1→3):
1. **Ingest** a denied claim from an 835 → parse → **triage** (class + priority) →
   compute **appeal deadline** → write rows + append-only audit.
2. **Correct** an easy denial (data-only) → **guardrail gate** → generate a valid
   **837P** → **submit** to the (simulated) clearinghouse → **277CA accepted** →
   **835 paid** (loop closed).
3. **Block** any upcode attempt (modifier/CPT/units/charge/E&M/invented ICD) →
   no EDI, routed to human coder, logged.
4. **Appeal** a medical-necessity denial → **RAG** over the policy index → letter
   citing the payer's own LCD criteria, with a PHI header assembled locally.
5. Serve a **read-only API**: health, denial queue (by `$ × p(win)`), deadlines
   at risk.

**Bottom line on capability:** the *decision logic and safety architecture* are
solid and well-tested (especially the guardrail). The *integrations, real data,
real model quality, human-review UI, learning loop, and production hosting* are
not there yet. It's a strong, secure skeleton — not yet a system that has
recovered a real dollar.

---

## 7. What's left from the original spec (priority order)

**To earn the first real dollar (finish Phase 1):**
1. **1.7 Outcome ingestion** — match returned 835s to submitted claims/appeals,
   write `appeal.outcome` + `recovered_amount`, populate the first
   `appeal_outcome` (moat) row. _Closes the learning loop; small, high-leverage._
2. **1.6 Human review console** — queue + original-vs-proposed diff +
   approve/reject/edit + one-click submit. _The CPC signs coding; required before
   any real claim goes out. Needs API auth (RBAC) too._
3. **1.8 Contingency billing** — track recovered $, invoice 25%.
4. **Real clearinghouse adapter (1.4 hardening)** — Availity/Office Ally SFTP/API;
   harden the 277CA/835 parsers against real-payer output.
5. **0.3 One real PM/EHR read-only integration** (Athena or DrChrono) — gated on a
   BAA + a pilot practice.

**To build the moat (Phase 2):**
6. **2.1** Feed measured win rates back into triage ranking + appeal strategy.
7. **2.2** Commercial payer policy ingestion (real PDFs) + **0.6 live LCD scraper**
   + a **real embeddings model**.
8. **2.3** Prior-auth agent (portal RPA + fax). **2.4** exceptions-only review.
   **2.5** practice dashboard.

**Production hardening (cross-cutting):**
9. Workflow engine (Temporal/Inngest) for multi-day appeal/auth workflows +
   deadline **alerting** (T-30/14/7 notifications).
10. AWS HIPAA IaC (KMS, VPC, RDS, IAM), API auth/RBAC, SOC 2 path.
11. Expand CARC coverage toward the full set; broaden corrections beyond the easy
    class (always guardrail-gated).

**Business/legal (parallel, non-code):** BAA, healthcare attorney, E&O + cyber
insurance, a CPC on staff, phone-validate the wedge with 5 practices.

---

## 8. Repo map (for whoever picks this up)

```
src/rcm/
  guardrail/   ★ the fraud firewall (pure, unit-tested, CI-gated)
  core/        config, crypto (PHI enc), logging (PHI redaction), db
  models/      SQLAlchemy schema (spec §6) — PHI columns encrypted
  edi/         X12 835 parser
  taxonomy/    CARC → triage class
  deadlines/   timely-filing / appeal-window calculator
  triage/      TRIAGE v0 (classify + rank)
  policy/      LCD/NCD seed + embeddings (pgvector)
  llm/         Claude client + PHI de-identification (fail-closed)
  audit/       append-only writer
  api/         read-only FastAPI
  claims/      ★ write path: Claim837, corrections agent, 837P gen, guardrail-gated pipeline
  clearinghouse/  277CA, Clearinghouse Protocol, simulated round trip
  appeals/     ★ appeal agent: retriever (RAG) + drafter (PHI-safe) + agent
scripts/       gen_synthetic_835, ingest_835, scrape_lcd, dev_db.sh, demo_837p
tests/         107 tests (guardrail adversarial gate is the compliance gate)
docs/          BUILD_PLAN.md, this file · SECURITY.md · COMPLIANCE.md (repo root)
```

Run the compliance gate + all infra-free tests: `pytest -m "not postgres" -q`.
Full suite (needs Postgres): see README "No Docker?" section.
```
