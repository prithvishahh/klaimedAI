# Klaimed Denial Recovery Console (demo)

A browser UI over the real RCM engine. Every document and number shown is produced
by the actual modules (835 parser, triage, corrections, guardrail, 837P generator,
appeal drafter). The only staged part is the input: a synthetic 835 with fake PHI.

## Run

```bash
cd ~/Desktop/medical\ rcm
source .venv/bin/activate
python -m demo.server        # http://localhost:8800
```

No database needed (dev key + offline embeddings are self-defaulted).

## Features

- **KPI dashboard** with live contingency math (recoverable, recovered, Klaimed
  fee at 25%, net to the practice, in-queue count, at-risk ≤30d).
- **Work queue** with search, payer/status filters, per-claim status lifecycle
  (open → submitted → paid / escalated), and appeal-deadline risk.
- **Work all fixable** — one click auto-submits every data-fixable claim.
- **Claim detail** — the denial reason, the exact data-only fix (diff, codes
  unchanged), the guardrail verdict, and the resubmittable 837P (downloadable).
- **Appeals** cite the payer's own coverage policy; **bundling** escalates to a
  human coder (never auto-touched).
- **Activity feed** — an append-only, timestamped audit trail of every action.
- **CSV export** of the queue.

## The demo flow (for a screen-share)

1. **Load sample 835** → the backlog appears as a ranked work queue; the KPI strip
   fills in ($830 recoverable, 1 claim at risk).
2. Click **SMITH, MICHAEL (CO-16)** → the denial reason, the data-only fix
   (`SMITH → SMYTHE`, **codes unchanged**), the guardrail **ALLOW**, and the
   corrected **837P** (Download button).
3. Click **⚡ Work all fixable** → three claims auto-submit; Recovered jumps to
   $610 (fee $153, net $458), statuses flip to **paid**, the activity feed logs it.
4. Click **KIM, DAVID (CO-50)** → a medical-necessity **appeal** citing the payer's
   own policy. **GOMEZ, LISA (CO-97)** → escalated to a human coder.
