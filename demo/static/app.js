"use strict";
const $ = (s) => document.querySelector(s);
const money = (n) => "$" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
let allRows = [];
let selected = null;

async function jget(url) { return (await fetch(url)).json(); }
async function jpost(url, body) { return (await fetch(url, { method: "POST", body: body || "" })).json(); }

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ---------- intake ---------- */
function wireIntake() {
  const drop = $("#drop"), file = $("#file");
  file.addEventListener("change", () => {
    if (file.files[0]) file.files[0].text().then((t) => { $("#dropText").textContent = file.files[0].name; ingest(t); });
  });
  ["dragover", "dragenter"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const f = ev.dataTransfer.files[0];
    if (f) f.text().then((t) => { $("#dropText").textContent = f.name; ingest(t); });
  });
  $("#loadSample").addEventListener("click", async () => {
    $("#dropText").textContent = "sample.835";
    ingest(await (await fetch("/api/sample-835")).text());
  });
  $("#search").addEventListener("input", renderQueue);
  $("#payerFilter").addEventListener("change", renderQueue);
  $("#statusFilter").addEventListener("change", renderQueue);
  $("#workAll").addEventListener("click", workAll);
}

async function ingest(text) {
  const data = await jpost("/api/ingest", text);
  allRows = data.rows;
  $("#queuePanel").classList.remove("hidden");
  const pf = $("#payerFilter");
  pf.innerHTML = '<option value="">All payers</option>' + data.payers.map((p) => `<option>${p}</option>`).join("");
  renderKPIs(data.summary);
  renderQueue();
  refreshActivity();
  toast(`Parsed ${data.rows.length} denials · ${money(data.summary.recoverable)} recoverable`);
}

/* ---------- KPIs ---------- */
function renderKPIs(s, flash) {
  const set = (id, v) => { const el = $(id); el.textContent = v; if (flash) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); } };
  set("#kpiQueue", s.in_queue);
  set("#kpiRecoverable", money(s.recoverable));
  set("#kpiRecovered", money(s.recovered));
  set("#kpiFee", money(s.fee));
  set("#kpiNet", money(s.net));
  const r = $("#kpiRisk"); r.textContent = s.at_risk;
  r.style.color = s.at_risk > 0 ? "var(--red)" : "";
}

/* ---------- queue (client-side filter) ---------- */
const kindLabel = { fix: "auto-fix", appeal: "appeal", escalate: "human coder" };
function renderQueue() {
  const q = $("#search").value.trim().toLowerCase();
  const pf = $("#payerFilter").value, sf = $("#statusFilter").value;
  const rows = allRows.filter((r) =>
    (!pf || r.payer === pf) && (!sf || r.status === sf) &&
    (!q || (r.patient + " " + r.cn + " " + r.payer).toLowerCase().includes(q)));
  $("#queueBody").innerHTML = rows.map((r) => `
    <tr data-cn="${r.cn}" class="${r.cn === selected ? "sel" : ""}">
      <td>${r.patient}</td><td>${r.payer}</td><td class="carc">${r.carc}</td>
      <td class="r">${money(r.denied)}</td>
      <td><span class="badge badge--${r.kind}">${kindLabel[r.kind]}</span></td>
      <td><span class="status status--${r.status}">${r.status}</span></td>
      <td class="r">${r.priority}</td>
      <td><span class="risk risk--${r.risk}">${r.days_left}d</span></td>
    </tr>`).join("") || `<tr><td colspan="8" style="color:var(--muted);padding:1rem">No matching claims.</td></tr>`;
  $("#queueBody").querySelectorAll("tr[data-cn]").forEach((tr) =>
    tr.addEventListener("click", () => selectCase(tr.dataset.cn)));
}

function setRowStatus(cn, status, recovered) {
  const row = allRows.find((r) => r.cn === cn);
  if (row) { row.status = status; if (recovered != null) row.recovered = recovered; }
}

/* ---------- detail ---------- */
async function selectCase(cn) {
  selected = cn;
  document.querySelectorAll("#queueBody tr").forEach((tr) => tr.classList.toggle("sel", tr.dataset.cn === cn));
  renderDetail(await jget(`/api/case/${cn}`));
}

function ediHtml(segs) {
  return segs.map((s) => {
    const i = s.indexOf("*");
    if (i < 0) return `<span class="seg">${s}</span>`;
    return `<span class="tag">${s.slice(0, i)}</span><span class="seg">${s.slice(i)}</span>`;
  }).join("\n");
}

function renderDetail(d) {
  $("#detailEmpty").classList.add("hidden");
  const detail = $("#detail"); detail.classList.remove("hidden");
  const done = d.status === "paid";
  let body = "";
  if (d.kind === "fix") {
    body = `
      <div class="d-section"><h3>What Klaimed is doing</h3><p class="d-plan">${d.plan}</p></div>
      <div class="d-section"><h3>The fix (data only)</h3>
        <div class="diff">${d.changes.map((c) => `
          <div class="diff__row"><span class="diff__field">${c.field}</span>
            <span class="diff__before">${c.before}</span><span class="diff__arrow">→</span>
            <span class="diff__after">${c.after}</span></div>`).join("")}</div>
        <div style="margin-top:.7rem;display:flex;gap:.5rem;flex-wrap:wrap">
          <span class="pill pill--unchanged">Procedure codes UNCHANGED · ${d.codes_unchanged.join(", ")}</span>
          <span class="pill pill--ok">✓ Guardrail: ${String(d.verdict).toUpperCase()}</span>
        </div></div>
      <div class="d-section"><h3>Corrected claim · ready to resubmit</h3>
        <p class="edi-summary">A standards-compliant <b>837P</b> claim for <b>${d.cpt}</b> · ${money(d.denied)} · payer <b>${d.payer}</b>, with the corrected data and <b>codes unchanged</b>. This is the exact file we send back to the clearinghouse.</p>
        <details class="edi-toggle">
          <summary>Show raw EDI · ${d.edi.length} segments</summary>
          <div class="edi"><pre>${ediHtml(d.edi)}</pre></div>
        </details>
        <a class="btn btn--ghost btn--sm" style="margin-top:.6rem" href="/api/case/${d.cn}/837" download>Download 837P</a>
      </div>`;
  } else if (d.kind === "appeal") {
    body = `
      <div class="d-section"><h3>What Klaimed is doing</h3><p class="d-plan">${d.plan}</p></div>
      <div class="d-section"><h3>Appeal · citing the payer's own policy</h3>
        <div class="cites">${d.cited_policies.map((p) => `<span class="cite">${p}</span>`).join("")}</div>
        <div style="margin-top:.6rem"><span class="pill pill--unchanged">Codes argued UNCHANGED · ${d.codes_unchanged.join(", ")}</span></div>
        <div class="letter">${(d.letter || "").replace(/</g, "&lt;")}</div></div>`;
  } else {
    body = `<div class="d-section"><h3>What Klaimed is doing</h3><p class="d-plan">${d.plan}</p></div>
      <div class="escalate-card">${d.note}</div>`;
  }

  const actions = d.kind === "escalate" ? "" : (done
    ? `<div class="d-actions"><span class="submit-result">✓ Recovered ${money(d.recovered)} · 835 PAID</span></div>`
    : `<div class="d-actions"><button class="btn btn--primary" id="submitBtn">Submit &amp; recover ${money(d.denied)}</button></div><div id="actionOut"></div>`);

  detail.innerHTML = `
    <div class="d-head">
      <div class="d-patient">${d.patient} <span class="status status--${d.status}">${d.status}</span></div>
      <div class="d-meta">
        <span>Claim <b>${d.cn}</b></span><span>Payer <b>${d.payer}</b></span>
        <span>CPT <b>${d.cpt}</b></span><span>Dx <b>${d.dx.join(", ")}</b></span>
        <span>Denied <b>${money(d.denied)}</b></span>
        <span>Deadline <b>${d.days_left}d</b> (${d.risk})</span>
      </div>
      <div class="d-reason"><b>${d.carc}</b> — ${d.reason}</div>
    </div>${body}${actions}`;

  if (d.kind !== "escalate" && !done) $("#submitBtn").addEventListener("click", () => doSubmit(d.cn));
}

async function doSubmit(cn) {
  const r = await jpost(`/api/case/${cn}/submit`);
  if (!r.submittable) { $("#actionOut").innerHTML = `<div class="escalate-card">${r.note}</div>`; return; }
  renderKPIs(r.summary, true);
  setRowStatus(cn, r.paid ? "paid" : "submitted", r.recovered);
  renderQueue();
  refreshActivity();
  if (selected === cn) selectCase(cn);
  toast(`${r.ack} → ${r.era}` + (r.paid ? ` · recovered ${money(r.recovered)}` : ""));
}

async function workAll() {
  const r = await jpost("/api/workall");
  allRows = r.rows;
  renderKPIs(r.summary, true);
  renderQueue();
  refreshActivity();
  if (selected) selectCase(selected);
  toast(`Auto-fixed ${r.count} claims · recovered ${money(r.recovered)}`);
}

/* ---------- activity ---------- */
async function refreshActivity() {
  const { events } = await jget("/api/activity");
  const el = $("#activity");
  if (!events.length) { el.innerHTML = `<li class="activity__empty">No activity yet.</li>`; return; }
  el.innerHTML = events.map((e) => `
    <li><span class="activity__ts">${e.ts}</span>
        <span class="activity__actor">${e.actor}</span>
        <span>${e.text}</span></li>`).join("");
}

function init() { wireIntake(); }
init();
