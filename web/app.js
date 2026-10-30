import { regrade, referenceCapacity, ORDER } from "./grading.js";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (x, d = 3) => (x == null || !Number.isFinite(+x) ? "–" : (+x).toLocaleString("en-US", { maximumFractionDigits: d }));
const FAULTS = {
  LOW_CAPACITY: ["Low capacity", "LC"], HIGH_IR: ["High resistance", "IR"], CURVE_SHAPE: ["Curve shape", "CS"],
  CAPACITY_CREEP_UP: ["Capacity creep", "CR"], LOW_CE: ["Low first-cycle CE", "CE"], NOISY_OR_DEAD_CHANNEL: ["Noisy or dead", "ND"],
};
const GRADE_TEXT = { A: "A", B: "B", C: "C", REJECT: "R" };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const app = $("#app");
let S = null; // current run state

async function getJSON(u) { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(`${u}: HTTP ${r.status}`); return r.json(); }
async function getText(u) { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(`${u}: HTTP ${r.status}`); return r.text(); }
async function loadIndex() {
  const out = [];
  for (const f of ["runs/index.json", "runs/index.local.json"]) { try { out.push(...(await getJSON(f))); } catch { /* optional */ } }
  return out;
}

// ------------------------------------------------------------------ routing
window.addEventListener("hashchange", route);
route();
function route() {
  if (S?.timer) clearTimeout(S.timer);
  const m = location.hash.match(/^#\/run\/([^?]+)/);
  if (m) renderRun(decodeURIComponent(m[1])); else renderHome();
  app.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ home
async function renderHome() {
  S = null;
  document.title = "Vera · battery cell QC agent";
  app.innerHTML = `
  <section class="hero">
    <div>
      <h1>Drop in a raw formation or grading tester export, in any layout. Get every cell graded, the bad ones flagged with evidence, and a report you can check.</h1>
      <p>Every tester exports a different file layout, faults are subtle, and a wrong call costs money both ways. Vera reads the
        unfamiliar file itself, computes every number with code, and uses NVIDIA Nemotron only where language helps:
        understanding the layout, writing and repairing the conversion code, and explaining the findings.</p>
      <p>Below are recorded runs. Open one to replay what the agent did, step by step.</p>
    </div>
    <div class="card steps"><h2>How it works</h2><ol>
      <li><b>Peek</b> at the file's structure <span class="who">code</span></li>
      <li><b>Write a converter</b> to Vera's canonical table <span class="who">Nemotron, planner</span></li>
      <li><b>Run it in isolation</b>, check units, sign and time; repair on failure (up to 3 times) <span class="who">sandbox + code</span></li>
      <li><b>Compute</b> capacity, efficiency, resistance and curve shape, then flag and grade <span class="who">code</span></li>
      <li><b>Explain</b> the flags and write the summary; every number is checked against the results <span class="who">Nemotron, worker + verifier</span></li>
      <li><b>Remember</b> the layout, so the next file like it skips steps 2–3 <span class="who">memory</span></li>
    </ol></div>
  </section>
  <h2 class="section-title">Recorded runs</h2>
  <div class="runs" id="runs"><p class="loading">Loading runs…</p></div>
  <div id="measured"></div>
  <h2 class="section-title">Run Vera on your own export</h2>
  <div class="card local"><p class="note">This page only replays recorded runs. To analyse your own file, run Vera locally with a free
    NVIDIA API key from build.nvidia.com (or a Nebius Token Factory key):</p>
    <pre>git clone https://github.com/Akshit-afk-dot/vera &amp;&amp; cd vera
uv sync &amp;&amp; cp .env.example .env    # then set NVIDIA_API_KEY in .env
uv run python -m agent run path/to/export.csv --label REAL --publish</pre></div>`;
  const runs = await loadIndex();
  $("#runs").innerHTML = runs.length ? runs.map(runCard).join("") :
    `<p class="empty">No recorded runs are published yet.</p>`;
  try {
    const r2 = await getJSON("data/r2.json");
    $("#measured").innerHTML = `<h2 class="section-title">Measured, not claimed</h2><div class="card local measured">${r2Table(r2)}</div>`;
  } catch { /* results not published yet */ }
}

function gradeBar(gc, n) {
  return `<div class="bar" aria-hidden="true">${ORDER.map((g) => `<span style="width:${(100 * (gc[g] || 0)) / Math.max(n, 1)}%;background:var(--${g})"></span>`).join("")}</div>`;
}
function runCard(r) {
  const dev = r.provider === "scripted";
  return `<a class="card runcard" href="#/run/${encodeURIComponent(r.id)}">
    <div style="display:flex;gap:8px;align-items:center;justify-content:space-between"><h3>${esc(r.name)}</h3><span class="label ${esc(r.data_label)}">${esc(r.data_label)}</span></div>
    ${gradeBar(r.grade_counts, r.n_channels)}
    <div class="meta">${r.n_channels} channels · ${r.n_flagged} flagged · ${r.repairs} self-repair${r.repairs === 1 ? "" : "s"}${r.memory_hit ? " · learned format reused" : ""}</div>
    <div class="meta">${dev ? "<b>dev run, scripted model</b>" : `${esc(r.models.planner)} + ${esc(r.models.worker)}`} · ${fmt(r.duration_s, 0)} s · ${fmt(r.tokens, 0)} tokens</div>
  </a>`;
}
function r2Table(r) {
  const rows = Object.entries(r.methods).map(([k, e]) => `<tr><td>${esc(k)}</td><td>${fmt(e.detection.precision, 2)}</td><td>${fmt(e.detection.recall, 2)}</td><td>${fmt(e.detection.f1, 2)}</td><td>${(100 * e.detection.false_alarm_rate_clean_batches).toFixed(2)}%</td></tr>`).join("");
  return `<p class="note"><span class="label SYNTHETIC">SYNTHETIC</span> Planted-fault detection on ${r.faulty_seeds.length} simulated 128-channel batches (${r.n_faulty_channels} faults) and ${r.clean_seeds.length} clean ones. The rules were developed on the same simulator, so treat these as optimistic.</p>
  <table><thead><tr><th>Method</th><th>Precision</th><th>Recall</th><th>F1</th><th>False alarms (clean batches)</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ------------------------------------------------------------------ run view
async function renderRun(id) {
  app.innerHTML = `<p class="loading">Loading run…</p>`;
  const base = `runs/${encodeURIComponent(id)}/`;
  let events, results, curves, report;
  try {
    [events, results, curves, report] = await Promise.all([
      getText(base + "events.jsonl").then((t) => t.trim().split("\n").map((l) => JSON.parse(l))),
      getJSON(base + "results.json"), getJSON(base + "curves.json"), getText(base + "report.md")]);
  } catch (e) {
    app.innerHTML = `<p class="empty">Could not load this run (${esc(e.message)}). <a href="#/">Back to runs</a></p>`;
    return;
  }
  const start = events[0], end = events[events.length - 1];
  S = { id, base, events, results, curves, report, shown: 0, timer: null, speed: 1, tab: "batch", mode: "grade",
    selected: null, th: structuredClone(results.thresholds), grades: results.channels.map((c) => c.grade),
    showResults: false, showReport: false };
  document.title = `${results.source_name} · Vera`;
  $("#powered").textContent = start.provider === "nebius" ? "Powered by NVIDIA Nemotron on Nebius Token Factory"
    : start.provider === "nvidia" ? "Powered by NVIDIA Nemotron via the NVIDIA API" : "Development run";
  const dev = start.provider === "scripted";
  app.innerHTML = `
    ${dev ? `<p class="card local"><b>Development run.</b> A scripted stand-in replaced the model; this run is local only and never published.</p>` : ""}
    <section class="card runbar">
      <div><h1>${esc(results.source_name)} <span class="label ${esc(results.data_label)}">${esc(results.data_label)}</span></h1>
        <div class="meta">planner <code>${esc(start.models.planner)}</code> · worker <code>${esc(start.models.worker)}</code> · runner <code>${esc(start.runner)}</code></div></div>
      <div class="stats"><span>time <b>${fmt(end.duration_s, 0)} s</b></span><span>tokens <b>${fmt((end.tokens_in || 0) + (end.tokens_out || 0), 0)}</b></span>
        <span>cost <b>${end.cost_usd ? "$" + fmt(end.cost_usd, 4) : "free tier"}</b></span></div>
      <div class="controls"><label class="note">speed <select id="speed"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
        <button id="skip" class="primary">Skip to results</button><button id="replay">Replay</button></div>
      <div class="progress" aria-hidden="true"><div id="prog"></div></div>
    </section>
    <div class="layout">
      <section class="card timeline" aria-label="Agent timeline"><h2>Agent timeline</h2><div id="tl" aria-live="polite"></div></section>
      <section class="card panel">
        <div class="tabs" role="tablist">${["batch", "channel", "report", "thresholds"].map((t) => `<button role="tab" data-tab="${t}" aria-selected="false">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>
        <div id="pane"></div>
      </section>
    </div>`;
  $("#skip").onclick = () => { while (S.shown < S.events.length) step(true); };
  $("#replay").onclick = () => { clearTimeout(S.timer); S.shown = 0; S.showResults = S.showReport = false; $("#tl").innerHTML = ""; renderPane(); tick(); };
  $("#speed").onchange = (e) => { S.speed = +e.target.value; };
  app.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { S.tab = b.dataset.tab; renderPane(); }));
  renderPane();
  tick();
}

function tick() {
  if (S.shown >= S.events.length) return;
  step(false);
  if (S.shown < S.events.length) {
    const gap = (Date.parse(S.events[S.shown].ts) - Date.parse(S.events[S.shown - 1].ts)) / 1000;
    S.timer = setTimeout(tick, (Math.min(Math.max(gap, 0.25), 1.4) * 1000) / S.speed);
  }
}
function step(fast) {
  const ev = S.events[S.shown++];
  const html = eventHTML(ev);
  if (html) $("#tl").insertAdjacentHTML("beforeend", html);
  if (!fast) { const tl = $("#tl").parentElement; tl.scrollTop = tl.scrollHeight; }
  $("#prog").style.width = `${(100 * S.shown) / S.events.length}%`;
  if (ev.type === "results.ready") { S.showResults = true; renderPane(); }
  if (ev.type === "report.ready") { S.showReport = true; renderPane(); }
  if (S.shown === S.events.length) { $("#skip").disabled = true; }
}

function eventHTML(e) {
  const box = (cls, title, body = "") => `<div class="ev ${cls}"><div class="t">${title}</div>${body}</div>`;
  const pre = (label, text) => (text ? `<details><summary>${label}</summary><pre>${esc(text)}</pre></details>` : "");
  switch (e.type) {
    case "run.started": return box("", `Run started`, `<div class="d">${esc(e.source.name)} · ${fmt(e.source.size_bytes / 1e6, 1)} MB · sha256 ${esc(e.source.sha256.slice(0, 12))}…</div>`);
    case "memory.hit": return box("memory", `Recognised a learned layout`, `<div class="d">fingerprint ${esc(e.fingerprint)}, learned ${esc(e.saved_at.slice(0, 10))}: reusing its converter (still validated)</div>`);
    case "llm.call": return box("llm", `<span class="chip nv">Nemotron · ${esc(e.role)}</span> ${esc(e.purpose)}`,
      `<div class="ev-line">${esc(e.model)} · ${fmt(e.tokens_in, 0)} → ${fmt(e.tokens_out, 0)} tokens · ${fmt(e.latency_ms / 1000, 1)} s</div>`);
    case "code.generated": return box("code", `Code written <span class="chip">${esc(e.code_id)}</span> attempt ${e.attempt}`, pre("show code", e.code));
    case "schema.proposed": return "";
    case "sandbox.started": return box("sandbox", `Running ${esc(e.code_id)} in isolation <span class="chip">${esc(e.runner)}</span>`);
    case "sandbox.finished": return e.ok ? box("ok", `Ran in ${fmt(e.duration_s, 1)} s`, `<div class="ev-line">${esc(e.stdout_tail.trim().slice(0, 140))}</div>`)
      : box("fail", `Run failed (exit ${e.exit_code ?? "timeout"})`, pre("show error", e.stderr_tail));
    case "schema.validated": return box(e.ok ? "ok" : "fail", e.ok ? `Output passed ${e.checks.length} checks` : `Output failed validation`,
      `${e.ok ? `<div class="d">${fmt(e.n_channels, 0)} channels · ${fmt(e.n_cycles, 0)} cycles · ${fmt(e.n_rows, 0)} rows</div>` : ""}<ul class="checks">${e.checks.map((c) => `<li class="${c.ok ? "" : "no"}">${esc(c.name)}: <span class="d">${esc(c.detail)}</span></li>`).join("")}</ul>`);
    case "repair.attempt": return box("repair", `Self-repair ${e.attempt} of ${e.max_attempts}`, `<div class="d">${esc(e.error_summary)}</div>`);
    case "analysis.progress": return box("", `Features computed for ${e.done} ${esc(e.unit)}`, `<div class="d">capacity, efficiency, resistance, curve shape, noise · analysis/features.py</div>`);
    case "thresholds.proposed": return box("", `Grade bins set (${esc(e.thresholds.source)})`, `<div class="d">${esc(e.thresholds.rationale)}</div>`);
    case "results.ready": return box("ok", `Results: ${e.summary.n_channels} channels, ${e.summary.n_flagged} flagged`, gradeBar(e.summary.grade_counts, e.summary.n_channels));
    case "verify.claim_failed": return box("verify", `Claim rejected, sentence ${esc(e.action)}`, `<div class="d"><del>${esc(e.sentence)}</del><br>${esc(e.claim)}: ${esc(e.reason)}</div>`);
    case "verify.summary": return box("verify", `Verified ${e.claims_checked} sentences`, `<div class="d">${e.claims_failed} failed · ${e.sentences_regenerated} regenerated · ${e.sentences_dropped} dropped</div>`);
    case "report.ready": return box("ok", "Report ready");
    case "run.finished": return box("ok", `Done in ${fmt(e.duration_s, 0)} s`, `<div class="ev-line">${fmt(e.tokens_in + e.tokens_out, 0)} tokens · ${e.cost_usd ? "$" + fmt(e.cost_usd, 4) : "free tier"}</div>`);
    case "run.failed": return box("fail", `Run failed at ${esc(e.stage)}`, `<div class="d">${esc(e.error)}</div>`);
    default: return "";
  }
}

// ------------------------------------------------------------------ panel
function renderPane() {
  app.querySelectorAll("[data-tab]").forEach((b) => {
    const t = b.dataset.tab;
    b.setAttribute("aria-selected", String(t === S.tab));
    b.disabled = t === "report" ? !S.showReport : !S.showResults;
  });
  const pane = $("#pane");
  if (!S.showResults) { pane.innerHTML = `<p class="empty">Results appear here as the replay reaches them…</p>`; return; }
  if (S.tab === "report" && !S.showReport) S.tab = "batch";
  ({ batch: renderBatch, channel: renderChannel, report: renderReport, thresholds: renderThresholds })[S.tab](pane);
}

function counts() { const c = { A: 0, B: 0, C: 0, REJECT: 0 }; S.grades.forEach((g) => c[g]++); return c; }
function fill(ch, i) {
  if (S.mode === "grade") return css(`--${S.grades[i]}`);
  return ch.flags.length ? css(`--f-${ch.flags[0].type}`) : css("--none");
}

function renderBatch(pane) {
  const r = S.results, s = r.summary, gc = counts();
  const tile = (k, v) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  pane.innerHTML = `
    <div class="tiles">${tile("Channels", s.n_channels)}${tile("Flagged", s.n_flagged)}${ORDER.map((g) => tile(`Grade ${g === "REJECT" ? "Reject" : g}`, gc[g])).join("")}
      ${tile("Ref. capacity", fmt(s.reference_capacity_ah, 4) + " Ah")}${tile("Median IR", s.median_ir_mohm ? fmt(s.median_ir_mohm, 3) + " mΩ" : "–")}</div>
    <div class="heat-head"><h2 style="margin:0">Tray</h2>
      <div><label class="note">colour by <select id="mode"><option value="grade">grade</option><option value="fault">fault</option></select></label></div></div>
    <div class="legend">${S.mode === "grade" ? ORDER.map((g) => `<span><i style="background:var(--${g})"></i>${g === "REJECT" ? "Reject" : g}</span>`).join("")
      : Object.entries(FAULTS).map(([k, [n, ab]]) => `<span><i style="background:var(--f-${k})"></i>${ab} ${n}</span>`).join("") + `<span><i style="background:var(--none)"></i>no flag</span>`}</div>
    <div class="heat" id="heat"></div>
    <h2 style="margin-top:16px">Flagged channels</h2>
    <table><thead><tr><th>Channel</th><th>Grade</th><th>Flag</th><th>Evidence</th></tr></thead><tbody>
      ${flaggedRows().map(({ c, i, f }) => `<tr class="click" tabindex="0" data-ch="${esc(c.channel_id)}"><td><code>${esc(c.channel_id)}</code></td><td><span class="grade ${S.grades[i]}">${GRADE_TEXT[S.grades[i]]}</span></td>
        <td>${esc(FAULTS[f.type]?.[0] || f.type)} <span class="chip">${esc(f.severity)}</span></td><td class="ev-line">${evidence(f.evidence[0])}</td></tr>`).join("") || `<tr><td colspan="4" class="note">No channel was flagged.</td></tr>`}
    </tbody></table>`;
  $("#mode").value = S.mode;
  $("#mode").onchange = (e) => { S.mode = e.target.value; renderBatch(pane); };
  drawHeat($("#heat"));
  pane.querySelectorAll("tr[data-ch]").forEach((tr) => { const go = () => selectChannel(tr.dataset.ch); tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
}
function flaggedRows() {
  const rows = [];
  S.results.channels.forEach((c, i) => c.flags.forEach((f) => rows.push({ c, i, f })));
  const z = (f) => (f.evidence[0].robust_z == null ? 99 : Math.abs(f.evidence[0].robust_z));
  return rows.sort((a, b) => z(b.f) - z(a.f));
}
function evidence(e) {
  return `${esc(e.metric)} ${fmt(e.value, 4)} ${esc(e.unit)} vs median ${fmt(e.batch_median, 4)} · ${e.robust_z == null ? esc(e.threshold) : `z ${fmt(e.robust_z, 2)}`}`;
}

function drawHeat(el) {
  const ch = S.results.channels;
  const rows = Math.max(...ch.map((c) => c.position[0])) + 1, cols = Math.max(...ch.map((c) => c.position[1])) + 1;
  const sz = 34, pad = 24, W = pad + cols * sz, H = pad + rows * sz;
  const letterRows = ch.every((c) => /^[A-Za-z]\d+$/.test(c.channel_id));
  let s = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Tester tray, ${ch.length} channels">`;
  for (let c = 0; c < cols; c++) s += `<text x="${pad + c * sz + sz / 2}" y="14" text-anchor="middle">${c + 1}</text>`;
  for (let r = 0; r < rows; r++) s += `<text x="10" y="${pad + r * sz + sz / 2 + 4}" text-anchor="middle">${letterRows ? String.fromCharCode(65 + r) : r + 1}</text>`;
  ch.forEach((c, i) => {
    const [r, k] = c.position, x = pad + k * sz, y = pad + r * sz;
    const label = S.mode === "grade" ? GRADE_TEXT[S.grades[i]] : c.flags.length ? FAULTS[c.flags[0].type]?.[1] || "!" : "";
    const tip = `${c.channel_id}: grade ${S.grades[i]}, ${fmt(c.capacity_ah, 4)} Ah${c.flags.length ? ", " + c.flags.map((f) => FAULTS[f.type]?.[0] || f.type).join(", ") : ""}`;
    s += `<g class="c" tabindex="0" data-ch="${esc(c.channel_id)}" role="button" aria-label="${esc(tip)}">
      <rect class="cell${S.selected === c.channel_id ? " sel" : ""}" x="${x + 1}" y="${y + 1}" width="${sz - 2}" height="${sz - 2}" rx="5" fill="${fill(c, i)}"><title>${esc(tip)}</title></rect>
      <text class="in" x="${x + sz / 2}" y="${y + sz / 2 + 3.5}" text-anchor="middle">${label}</text>
      ${c.flags.length && S.mode === "grade" ? `<circle cx="${x + sz - 7}" cy="${y + 7}" r="3" fill="#111"/>` : ""}</g>`;
  });
  el.innerHTML = s + "</svg>";
  el.querySelectorAll("g.c").forEach((g) => { const go = () => selectChannel(g.dataset.ch); g.onclick = go; g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }; });
}

function selectChannel(id) { S.selected = id; S.tab = "channel"; renderPane(); }

function renderChannel(pane) {
  const chs = S.results.channels;
  if (!S.selected) S.selected = (chs.find((c) => c.flags.length) || chs[0]).channel_id;
  const i = chs.findIndex((c) => c.channel_id === S.selected), c = chs[i];
  const flagged = chs.filter((x) => x.flags.length).map((x) => x.channel_id);
  const fi = flagged.indexOf(c.channel_id);
  pane.innerHTML = `
    <div class="chhead"><h3>${esc(c.channel_id)}</h3><span class="grade ${S.grades[i]}">${GRADE_TEXT[S.grades[i]]}</span>
      <span class="note">${fmt(c.capacity_ah, 4)} Ah · ${c.ir_mohm == null ? "IR n/a" : fmt(c.ir_mohm, 3) + " mΩ"} · tray ${c.position[0] + 1}/${c.position[1] + 1}</span>
      <span style="margin-left:auto"><button id="prev" ${fi <= 0 ? "disabled" : ""}>← prev flagged</button> <button id="next" ${fi < 0 || fi >= flagged.length - 1 ? (fi < 0 && flagged.length ? "" : "disabled") : ""}>next flagged →</button></span></div>
    ${c.flags.length ? c.flags.map((f) => `<div class="flag"><div class="ft">${esc(FAULTS[f.type]?.[0] || f.type)} <span class="chip">${esc(f.severity)}</span></div><div class="ev-line">${evidence(f.evidence[0])} · rule: ${esc(f.evidence[0].threshold)}</div></div>`).join("")
      : `<p class="note">No flags on this channel.</p>`}
    ${c.explanation ? `<p><b>Explanation</b> <span class="chip nv">${S.events[0].provider === "scripted" ? "scripted" : "Nemotron worker"} · numbers verified</span><br>${esc(c.explanation)}</p>` : ""}
    <div class="chart" id="chart"></div>
    <div><table><thead><tr><th>Cycle</th><th>Dis. Ah</th><th>Chg. Ah</th><th>CE</th><th>IR mΩ</th><th>Mid V</th></tr></thead><tbody>
        ${c.cycles.map((y) => `<tr><td>${y.cycle}</td><td>${fmt(y.discharge_capacity_ah, 4)}</td><td>${fmt(y.charge_capacity_ah, 4)}</td><td>${fmt(y.ce, 4)}</td><td>${fmt(y.ir_mohm, 2)}</td><td>${fmt(y.mid_voltage_v, 3)}</td></tr>`).join("")}</tbody></table>
        <p class="note" style="margin-top:12px"><b>Provenance.</b> Converted by ${c.provenance.code_ids.map((k) => `<a href="#" data-code="${esc(k)}">${esc(k)}.py</a>`).join(", ")}
          (sha256 ${esc(c.provenance.code_sha256.slice(0, 12))}…); numbers from <code>analysis/features.py</code>, <code>rules.py</code>, <code>grading.py</code>.</p></div>`;
  $("#prev").onclick = () => selectChannel(flagged[fi - 1]);
  $("#next").onclick = () => selectChannel(flagged[fi < 0 ? 0 : fi + 1]);
  pane.querySelectorAll("[data-code]").forEach((a) => (a.onclick = async (e) => { e.preventDefault(); showCode(a.dataset.code); }));
  drawChart($("#chart"), c);
}

function medianChannel() {
  const caps = S.results.channels.filter((c) => c.capacity_ah > 0).sort((a, b) => a.capacity_ah - b.capacity_ah);
  return caps[Math.floor(caps.length / 2)];
}
function drawChart(el, c) {
  const cur = S.curves[c.channel_id] || {}, med = medianChannel(), medC = S.curves[med?.channel_id] || {};
  const cycles = Object.keys(cur).map(Number).sort((a, b) => a - b);
  const series = cycles.map((k, j) => ({ name: `cycle ${k}`, q: cur[k].q_ah, v: cur[k].v, color: `hsl(${210 - (j * 150) / Math.max(cycles.length - 1, 1)} 70% 45%)` }));
  const lastMed = Object.keys(medC).map(Number).sort((a, b) => a - b).pop();
  if (lastMed != null && med.channel_id !== c.channel_id) series.push({ name: `median channel ${med.channel_id}`, q: medC[lastMed].q_ah, v: medC[lastMed].v, color: css("--muted"), dash: true });
  if (!series.length) { el.innerHTML = `<p class="note">No discharge curve recorded for this channel.</p>`; return; }
  const W = 760, H = 300, L = 46, B = 34, T = 10, R = 10;
  const qs = series.flatMap((s) => s.q), vs = series.flatMap((s) => s.v);
  const qmax = Math.max(...qs, 0.001), vmin = Math.min(...vs), vmax = Math.max(...vs);
  const X = (q) => L + (q / qmax) * (W - L - R), Y = (v) => T + ((vmax - v) / Math.max(vmax - vmin, 1e-6)) * (H - T - B);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Discharge voltage versus capacity for ${esc(c.channel_id)}"><g class="axis">`;
  for (let k = 0; k <= 4; k++) {
    const q = (qmax * k) / 4, v = vmin + ((vmax - vmin) * k) / 4;
    s += `<line x1="${X(q)}" x2="${X(q)}" y1="${T}" y2="${H - B}"/><text x="${X(q)}" y="${H - B + 14}" text-anchor="middle">${fmt(q, 2)}</text>`;
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, 2)}</text>`;
  }
  s += `</g><text x="${(L + W) / 2}" y="${H - 4}" text-anchor="middle">discharged capacity (Ah)</text><text transform="translate(12 ${H / 2}) rotate(-90)" text-anchor="middle">voltage (V)</text>`;
  for (const sr of series) s += `<polyline fill="none" stroke="${sr.color}" stroke-width="${sr.dash ? 1.5 : 2}" ${sr.dash ? 'stroke-dasharray="5 4"' : ""} points="${sr.q.map((q, k) => `${X(q).toFixed(1)},${Y(sr.v[k]).toFixed(1)}`).join(" ")}"/>`;
  el.innerHTML = s + `</svg><div class="legend">${series.map((sr) => `<span><i style="background:${sr.color}"></i>${esc(sr.name)}</span>`).join("")}</div>`;
}

async function showCode(id) {
  const m = $("#modal");
  $("#modal-title").textContent = `${id}.py · written by Nemotron, run in isolation`;
  $("#modal-body").textContent = "Loading…";
  m.hidden = false;
  m.querySelector("[data-close]").focus();
  try { $("#modal-body").textContent = await getText(`${S.base}code/${id}.py`); } catch (e) { $("#modal-body").textContent = e.message; }
}
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close]")) $("#modal").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });

function renderReport(pane) { pane.innerHTML = `<article class="report">${markdown(S.report)}</article>`; }

function renderThresholds(pane) {
  const th = S.th;
  const row = (g) => `<label>${g} if capacity ≥</label><input type="number" step="0.5" data-cap="${g}" value="${th.capacity_min_pct[g]}"> <label>% and IR ≤</label><input type="number" step="1" data-ir="${g}" value="${th.ir_max_pct[g]}">`;
  pane.innerHTML = `
    <p>Grades are bins, not model opinions. Change them and the batch is regraded instantly by the same rules as
      <code>analysis/grading.py</code>; no model is called.</p>
    <div class="form">${["A", "B", "C"].map(row).join("")}
      <label>basis</label><select id="basis"><option value="batch_median">batch median</option><option value="nominal">nominal</option></select>
      <label>nominal Ah</label><input type="number" step="0.01" id="nominal" value="${th.nominal_capacity_ah ?? ""}"></div>
    <p class="note">Capacity bins are % of the reference capacity; IR bins are % of the batch median resistance. Flags still cap grades
      (high severity → C at best, medium → B) and noisy or dead channels are rejected.</p>
    <button class="primary" id="apply">Regrade</button> <button id="reset">Reset</button>
    <div class="diff" id="diff" aria-live="polite"></div>`;
  $("#basis").value = th.basis;
  $("#apply").onclick = () => {
    const nt = structuredClone(th);
    pane.querySelectorAll("[data-cap]").forEach((i) => (nt.capacity_min_pct[i.dataset.cap] = +i.value));
    pane.querySelectorAll("[data-ir]").forEach((i) => (nt.ir_max_pct[i.dataset.ir] = +i.value));
    nt.basis = $("#basis").value; nt.nominal_capacity_ah = $("#nominal").value ? +$("#nominal").value : null; nt.source = "user";
    try {
      const g = regrade(S.results, nt);
      const changed = g.filter((x, k) => x !== S.grades[k]).length;
      S.grades = g; S.th = nt;
      const c = counts();
      $("#diff").innerHTML = `Regraded with reference ${fmt(referenceCapacity(S.results.channels, nt), 4)} Ah: <b>${changed}</b> channel${changed === 1 ? "" : "s"} changed grade. Now ${ORDER.map((k) => `${k} ${c[k]}`).join(" · ")}.`;
    } catch (e) { $("#diff").textContent = e.message; }
  };
  $("#reset").onclick = () => { S.th = structuredClone(S.results.thresholds); S.grades = S.results.channels.map((c) => c.grade); renderThresholds(pane); $("#diff").textContent = "Reset to the run's thresholds."; };
}

// ------------------------------------------------------------------ minimal markdown (report only)
function inline(s) {
  return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>").replace(/(^|\W)_([^_]+)_(?=\W|$)/g, "$1<i>$2</i>");
}
function markdown(md) {
  const lines = md.split("\n"), out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^#{1,3} /.test(l)) { const n = l.match(/^#+/)[0].length; out.push(`<h${n}>${inline(l.slice(n + 1))}</h${n}>`); }
    else if (l.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      i--;
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      out.push(`<table><thead><tr>${cells(rows[0]).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(2).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else if (l.startsWith("- ")) {
      const items = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2));
      i--;
      out.push(`<ul>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>`);
    } else if (l.trim()) out.push(`<p>${inline(l)}</p>`);
  }
  return out.join("\n");
}
