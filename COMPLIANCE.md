# HIPAA & Regulatory Compliance

This maps the Phase 0 build to HIPAA Security Rule controls and records the
legal prerequisites the spec (§9) makes non-negotiable before any real PHI is
touched.

## HIPAA Security Rule — technical safeguards

| Safeguard (45 CFR §164.312) | How it's met here |
|---|---|
| Access control — unique IDs, least privilege | Separate `rcm_migrator` / `rcm_app` DB roles; `rcm_app` cannot UPDATE/DELETE `audit_log`. App auth/RBAC lands with the human-review console (Phase 1). |
| Audit controls | Append-only `audit_log` (trigger + grants); every agent action, model, and `prompt_hash` recorded. |
| Integrity | AES-256-GCM is authenticated (AEAD) — tampered ciphertext is rejected. Append-only audit trail. |
| Transmission security | TLS for Postgres and HTTP in staging/prod (below). |
| Encryption at rest | `EncryptedString` columns; PHI is ciphertext in the database. |

## Encryption key management
- **Dev:** `RCM_MASTER_KEY` is a base64url 256-bit key in `.env` (gitignored).
- **Prod:** the master key is an **AWS KMS**-managed data key (envelope
  encryption). The application interface is unchanged; only key provisioning
  differs. Rotate on suspected exposure. Keys are never logged or committed.

## PHI de-identification for model calls
No PHI leaves the BAA boundary inside a prompt. `rcm/llm/deident.py` strips
structured identifiers and **fail-closes** if any remain. Policy documents
(LCD/NCD) are public and contain no PHI, so embedding them is unrestricted.

## Legal prerequisites BEFORE a single real PHI record (spec §9)
These are process gates, not code — tracked here so they are not skipped:
- [ ] **BAA** executed with every practice (and with every downstream
      subprocessor, including the model/hosting providers). No BAA = no PHI.
- [ ] **Healthcare attorney** engaged before the first contract.
- [ ] **E&O + cyber-liability** insurance bound.
- [ ] **Certified coder (CPC)** on staff/contract before Phase 1 — the fraud
      firewall / human-in-the-loop reviewer.
- [ ] Contract language: *commercially reasonable efforts*, liability capped at
      fees collected, consequential damages disclaimed. Claims are submitted
      under the **provider's NPI** — they attest to accuracy.
- [ ] **SOC 2 Type I** early; HIPAA posture from day zero.

## Production hosting (target; not provisioned in Phase 0)
- HIPAA-eligible services only, under a **signed AWS BAA** (or Aptible/Datica).
- KMS-encrypted RDS Postgres, private subnets/VPC, TLS in transit, no PHI in
  CloudWatch logs, encrypted backups, cyber-liability policy bound.
- This repo's Docker Compose is **local dev only**. The AWS HIPAA IaC
  (Terraform: KMS, VPC, RDS, IAM) is a separate, later deliverable.

## Scope of Phase 0
Read-only: ingest + triage of a denied-claim queue against **synthetic** 835s.
Zero writes, zero outbound claims, zero real PHI. The write path (837P,
clearinghouse), appeal drafting, and prior-auth are later phases and inherit
these controls (every outbound artifact passes the guardrail first).
