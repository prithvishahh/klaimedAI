# Klaimed

The AI billing department for medical practices. Klaimed ingests denied insurance
claims, works out what is wrong, and generates the corrected claim or an appeal —
behind a hard guardrail that makes upcoding impossible.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # set RCM_MASTER_KEY
```

## Test

```bash
pytest -m "not postgres"      # fast suite, no database needed
```

## Demo

```bash
python -m demo.server         # http://localhost:8800
```

Upload an 835 remittance (or load the sample) to see denials get triaged, fixed,
and turned into resubmittable claims.
