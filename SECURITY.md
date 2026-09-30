# Security & Threat Model

This system handles Protected Health Information (PHI) and generates artifacts
that, if wrong, create **False Claims Act** exposure (treble damages, federal,
criminal). Security is not a feature bolted on later — it is the architecture.

## The two existential risks (spec §7, §9)

### 1. Systematic upcoding → False Claims Act
A model optimizing for collections will learn that adding a `-25` modifier or
bumping an E/M level gets claims paid. **"The model did it" is not a defense.**

**Control — the Guardrail (`rcm/guardrail/guardrail.py`):**
- A **pure, deterministic function**, no I/O, that every outbound claim/appeal
  must pass. It BLOCKs any change to CPT/HCPCS/ICD/modifier/units/charge/E&M that
  could increase reimbursement, and routes it to a certified human coder.
- **Unbypassable:** there is no flag, prompt, or config that disables a rule.
- **Adversarial test suite as a CI gate** (`tests/guardrail/test_adversarial.py`):
  if any upcoding vector ever passes, the build fails and nothing ships.
- The system is deliberately **incapable** of the most profitable fraud. That is
  a product differentiator: "architecturally cannot upcode — here's the audit log."

### 2. HIPAA breach / PHI disclosure
**Controls:**
- **Encryption at rest** — every PHI field is AES-256-GCM encrypted before it
  reaches Postgres (`rcm/core/crypto.py`, `EncryptedString` column type). A
  database compromise alone discloses no PHI. Fail-closed: no key → no start.
- **Encryption in transit** — TLS everywhere (Postgres `sslmode`, HTTPS at the
  edge) in staging/prod; documented in `COMPLIANCE.md`.
- **No PHI in logs** — `rcm/core/logging.py` redacts PHI keys and scrubs SSNs /
  long identifiers from every log event. Prompt bodies are never logged.
- **No PHI to models** — `rcm/llm/deident.py` de-identifies and **fail-closes**
  (`assert_deidentified`) before any model call. The audit log stores a
  `prompt_hash`, never the prompt body.
- **Append-only audit log** — `audit_log` cannot be updated or deleted: enforced
  by a Postgres trigger *and* by least-privilege role grants (`rcm_app` has no
  UPDATE/DELETE on it).
- **Least privilege** — separate `rcm_migrator` (DDL) and `rcm_app` (runtime)
  roles. Secrets come from the environment / a secrets manager, never the repo.

## Other risks (spec §9 risk table)
- **Missed timely-filing / appeal deadline → claim dead forever (our liability).**
  Control: `denial.appeal_deadline` is a first-class **indexed** object; the API
  surfaces at-risk denials at T-30/T-14/T-7. Full alerting is Phase 1.
- **Supply chain.** `pip-audit` (deps), `bandit` (SAST), and `gitleaks` (secret
  scanning) gate every merge (`.github/workflows/ci.yml`, `.pre-commit-config.yaml`).

## Data handling rules
- Real PHI never enters git. `.gitignore` blocks `.env`, `data/real/`, `*.phi`,
  and real `*.835` files. Only synthetic `*.sample.835` (fake PHI) is tracked.
- Reporting a vulnerability: contact the security owner (do not open a public
  issue). Rotate `RCM_MASTER_KEY` (KMS data key in prod) on any suspected exposure.

## Reviewing this repository
- The guardrail and its adversarial tests are the highest-signal review target.
- Run the compliance gate locally: `pytest -m "not postgres" -q`.
