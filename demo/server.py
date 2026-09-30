"""Klaimed demo console — FastAPI backend over the real RCM engine.

Run:  python -m demo.server        (serves http://localhost:8800)

Endpoints return JSON produced by the actual modules. The browser UI in
``demo/static`` renders it. Single-user, in-memory state — a demo, not prod.
"""

from __future__ import annotations

# --- zero-setup env (dev key + offline embeddings) BEFORE importing rcm ---
import base64
import os

os.environ.setdefault(
    "RCM_MASTER_KEY",
    base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode(),
)
os.environ.setdefault("RCM_EMBEDDING_DIM", "64")
os.environ.setdefault("RCM_ENV", "dev")

import csv  # noqa: E402
import io  # noqa: E402
from datetime import datetime  # noqa: E402
from decimal import ROUND_HALF_UP, Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from demo.scenario import BY_CN, CASES, RECEIVER, SUBMITTER, sample_835
from rcm.appeals.agent import draft_appeal  # noqa: E402
from rcm.appeals.model import AppealContext  # noqa: E402
from rcm.appeals.retriever import InMemoryRetriever  # noqa: E402
from rcm.claims.pipeline import (  # noqa: E402
    correct_and_prepare,
    prepare_outbound_837p,
    submit_outbound,
)
from rcm.clearinghouse.simulated import SimulatedClearinghouse  # noqa: E402
from rcm.deadlines.calculator import appeal_deadline, days_until, deadline_risk  # noqa: E402
from rcm.edi.x12_835 import parse_835, remittance_to_denials  # noqa: E402
from rcm.policy.scraper import scrape_policies  # noqa: E402
from rcm.triage.agent import triage  # noqa: E402

app = FastAPI(title="Klaimed Console")

_STATIC = Path(__file__).parent / "static"
_RETRIEVER = InMemoryRetriever(scrape_policies("dermatology"))
_CONTINGENCY = Decimal("0.25")  # our fee on recovered dollars
_EASY = {"140", "16", "27", "31"}
_CENTS = Decimal("0.01")

# --- in-memory demo state (reset on each ingest) ---
_STATUS: dict[str, str] = {}      # control_number -> open|submitted|paid|escalated
_RECOVERED: dict[str, Decimal] = {}
_ACTIVITY: list[dict[str, str]] = []


def _kind(carc: str) -> str:
    if carc in _EASY:
        return "fix"
    if carc == "50":
        return "appeal"
    return "escalate"


def _log(actor: str, text: str) -> None:
    _ACTIVITY.append({"ts": datetime.now().strftime("%H:%M:%S"), "actor": actor, "text": text})


def _segments(edi: str) -> list[str]:
    return [s + "~" for s in edi.split("~") if s.strip()]


def _outbound_for(cn: str):  # type: ignore[no-untyped-def]
    """The cleared outbound 837P for a case (fix -> corrected, appeal -> original)."""
    case = BY_CN[cn]
    if case.carc in _EASY:
        _res, outbound = correct_and_prepare(
            case.original, case.carc, case.context, submitter=SUBMITTER, receiver=RECEIVER
        )
        return outbound
    if case.carc == "50":
        return prepare_outbound_837p(
            case.original, case.original, submitter=SUBMITTER, receiver=RECEIVER
        )
    return None


def _queue_row(cn: str) -> dict[str, object]:
    case = BY_CN[cn]
    t = triage(case.carc, case.denied_amount)
    dl = appeal_deadline(case.denial_date, case.original.payer.name)
    return {
        "cn": cn,
        "patient": f"{case.original.subscriber.last_name}, {case.original.subscriber.first_name}",
        "payer": case.original.payer.name,
        "cpt": case.original.lines[0].cpt_code,
        "carc": f"CO-{case.carc}",
        "denied": float(case.denied_amount),
        "kind": _kind(case.carc),
        "klass": t.triage_class.value,
        "priority": round(float(t.priority)),
        "days_left": days_until(dl),
        "risk": deadline_risk(dl).value,
        "status": _STATUS.get(cn, "open"),
        "recovered": float(_RECOVERED.get(cn, 0)),
    }


def _queue_rows() -> list[dict[str, object]]:
    rows = [_queue_row(c.control_number) for c in CASES]
    rows.sort(key=lambda r: (r["status"] != "open", -float(r["priority"])))  # type: ignore[arg-type]
    return rows


def _summary() -> dict[str, object]:
    open_cns = [c.control_number for c in CASES if _STATUS.get(c.control_number) == "open"]
    recoverable = sum((BY_CN[cn].denied_amount for cn in open_cns), Decimal("0"))
    recovered = sum(_RECOVERED.values(), Decimal("0"))
    fee = (recovered * _CONTINGENCY).quantize(_CENTS, rounding=ROUND_HALF_UP)
    at_risk = 0
    for cn in open_cns:
        case = BY_CN[cn]
        if days_until(appeal_deadline(case.denial_date, case.original.payer.name)) <= 30:
            at_risk += 1
    return {
        "in_queue": len(open_cns),
        "recoverable": float(recoverable),
        "recovered": float(recovered),
        "fee": float(fee),
        "net": float(recovered - fee),
        "paid": sum(1 for s in _STATUS.values() if s == "paid"),
        "at_risk": at_risk,
    }


def _do_submit(cn: str) -> dict[str, object]:
    """Run one claim through the clearinghouse; update state; log; return the result."""
    case = BY_CN[cn]
    outbound = _outbound_for(cn)
    if outbound is None:
        return {"submittable": False, "note": "Escalated to a human coder — not auto-submitted."}
    ch = SimulatedClearinghouse(pay=True)
    receipt = submit_outbound(outbound, ch)
    remit = ch.remittance(receipt.control_number)
    denials = remittance_to_denials(parse_835(remit)) if remit else []
    paid = remit is not None and not denials
    recovered = case.denied_amount if paid else Decimal("0")
    _RECOVERED[cn] = recovered
    _STATUS[cn] = "paid" if paid else "submitted"
    strat = "appeal" if case.carc == "50" else "correction"
    _log("guardrail", f"{cn}: outbound 837P ALLOW (codes unchanged)")
    _log("clearinghouse",
         f"{cn}: 277CA {'ACCEPTED' if receipt.accepted else 'REJECTED'}"
         + (f" → 835 PAID, recovered ${recovered:.0f} via {strat}" if paid else ""))
    return {
        "submittable": True,
        "ack": "277CA ACCEPTED" if receipt.accepted else "277CA REJECTED",
        "accepted": receipt.accepted,
        "era": "835 PAID" if paid else "pending",
        "paid": paid,
        "recovered": float(recovered),
    }


# ----------------------------------------------------------------------------- routes


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/sample-835")
def get_sample() -> PlainTextResponse:
    return PlainTextResponse(sample_835())


@app.post("/api/ingest")
async def ingest(request: Request) -> JSONResponse:
    body = (await request.body()).decode("utf-8").strip()
    text = body or sample_835()
    denials = remittance_to_denials(parse_835(text))
    _STATUS.clear()
    _RECOVERED.clear()
    _ACTIVITY.clear()
    total = Decimal("0")
    matched = 0
    for d in denials:
        case = BY_CN.get(d.patient_control_number)
        if case is None:
            continue
        matched += 1
        total += d.denied_amount
        _STATUS[case.control_number] = "escalated" if _kind(case.carc) == "escalate" else "open"
    _log("parser", f"Parsed 835 remittance — {matched} denials, ${total:.0f} in disputed charges")
    _log("triage", "Ranked the queue by dollars × recovery probability; tracked appeal deadlines")
    payers = sorted({BY_CN[c].original.payer.name for c in _STATUS})
    return JSONResponse({"rows": _queue_rows(), "payers": payers, "summary": _summary()})


@app.get("/api/queue")
def queue() -> JSONResponse:
    return JSONResponse({"rows": _queue_rows(), "summary": _summary()})


@app.get("/api/summary")
def summary() -> JSONResponse:
    return JSONResponse(_summary())


@app.get("/api/activity")
def activity() -> JSONResponse:
    return JSONResponse({"events": list(reversed(_ACTIVITY))[:60]})


@app.get("/api/case/{cn}")
def case_detail(cn: str) -> JSONResponse:
    case = BY_CN.get(cn)
    if case is None:
        return JSONResponse({"error": "unknown claim"}, status_code=404)
    line = case.original.lines[0]
    t = triage(case.carc, case.denied_amount)
    dl = appeal_deadline(case.denial_date, case.original.payer.name)
    base: dict[str, object] = {
        "cn": cn,
        "patient": f"{case.original.subscriber.last_name}, {case.original.subscriber.first_name}",
        "member_id": case.original.subscriber.member_id,
        "payer": case.original.payer.name,
        "cpt": line.cpt_code,
        "dx": list(line.diagnosis_codes),
        "denied": float(case.denied_amount),
        "carc": f"CO-{case.carc}",
        "reason": case.reason,
        "klass": t.triage_class.value,
        "plan": case.plan,
        "status": _STATUS.get(cn, "open"),
        "denial_date": case.denial_date.isoformat(),
        "deadline": dl.isoformat(),
        "days_left": days_until(dl),
        "risk": deadline_risk(dl).value,
        "recovered": float(_RECOVERED.get(cn, 0)),
    }

    if case.carc in _EASY:
        result, outbound = correct_and_prepare(
            case.original, case.carc, case.context, submitter=SUBMITTER, receiver=RECEIVER
        )
        base.update({
            "kind": "fix",
            "changes": [{"field": c.field, "before": c.before, "after": c.after}
                        for c in result.changes],
            "codes_unchanged": [ln.cpt_code for ln in case.original.lines],
            "verdict": outbound.verdict.decision.value if outbound else "n/a",
            "strategy": result.strategy,
            "edi": _segments(outbound.edi_837p) if outbound else [],
        })
    elif case.carc == "50":
        appeal = draft_appeal(
            AppealContext(claim=case.original, carc_code="50", denied_amount=case.denied_amount),
            retriever=_RETRIEVER,
        )
        base.update({
            "kind": "appeal",
            "strategy": appeal.strategy,
            "cited_policies": list(appeal.cited_policies),
            "codes_unchanged": list(appeal.argued_cpt_codes),
            "letter": appeal.letter_text,
        })
    else:
        base.update({
            "kind": "escalate",
            "route": "human_coder",
            "note": "Bundling (CO-97) is the fraud danger zone. Klaimed never "
                    "auto-modifies it — it routes to a certified coder for review.",
        })
    return JSONResponse(base)


@app.get("/api/case/{cn}/837")
def download_837(cn: str) -> PlainTextResponse:
    outbound = _outbound_for(cn)
    edi = outbound.edi_837p if outbound else "no outbound claim for this denial"
    return PlainTextResponse(edi, headers={
        "Content-Disposition": f'attachment; filename="{cn}_corrected_837p.txt"'})


@app.post("/api/case/{cn}/submit")
def submit_case(cn: str) -> JSONResponse:
    if cn not in BY_CN:
        return JSONResponse({"error": "unknown claim"}, status_code=404)
    result = _do_submit(cn)
    return JSONResponse({**result, "summary": _summary()})


@app.post("/api/workall")
def work_all() -> JSONResponse:
    """Auto-submit every open, data-fixable claim (appeals stay for human review)."""
    done = 0
    recovered = Decimal("0")
    for c in CASES:
        if _STATUS.get(c.control_number) == "open" and _kind(c.carc) == "fix":
            r = _do_submit(c.control_number)
            if r.get("paid"):
                done += 1
                recovered += Decimal(str(r["recovered"]))
    _log("klaimed", f"Batch: auto-fixed {done} claims, recovered ${recovered:.0f}")
    return JSONResponse({"count": done, "recovered": float(recovered),
                         "rows": _queue_rows(), "summary": _summary()})


@app.get("/api/export.csv")
def export_csv() -> PlainTextResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Claim", "Patient", "Payer", "CARC", "Denied", "Action",
                "Priority", "DaysToDeadline", "Status", "Recovered"])
    for r in _queue_rows():
        w.writerow([r["cn"], r["patient"], r["payer"], r["carc"], r["denied"],
                    r["kind"], r["priority"], r["days_left"], r["status"], r["recovered"]])
    return PlainTextResponse(buf.getvalue(), headers={
        "Content-Disposition": 'attachment; filename="klaimed_queue.csv"',
        "Content-Type": "text/csv"})


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8800, log_level="warning")


if __name__ == "__main__":
    main()
