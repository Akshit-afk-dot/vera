# CLAUDE.md: Battery Cell QC Agent

Nebius × NVIDIA Global AI Hackathon · track **Best Apps & Agents** · team of 2 · submission closes **Fri Oct 30, 2026, 10:00 am PT (= 10:30 pm IST)**. Written Sun Oct 18, 2026 (IST); about 12 days remain. The project name is a working title: propose five human-sounding names in `docs/DESIGN.md`. **Chosen Oct 19: Vera** (repo at `C:\dev\vera` on Akshit's machine).

Tags used below: **VERIFIED** = read in the official docs or rules on Oct 17–18, 2026. **VERIFY** = unconfirmed, test it live before relying on it.

## 0. How to work

You are the lead engineer and designer. Two humans work with you: **Akshit** (agent core, evaluation, battery-domain knowledge) and a **partner** (product, UI, deploy, docs, video). Each may run their own Claude Code session in this repo.

- **Plan first.** Do Phase 0 (§10), then write `docs/DESIGN.md` (max 3 pages), then build in the phases of §11.
- **Decide, don't interrogate.** Ask the humans only when blocked on something that changes scope, costs money, or needs a credential. Otherwise decide, add one line to `docs/DECISIONS.md`, and move on.
- **Verify, don't assume.** Official docs index: https://docs.tokenfactory.nebius.com/llms.txt (every docs page also exists as `.md`). Re-read the hackathon rules (https://nebiusglobalaihackathon.devpost.com/rules) once now and once before submitting.
- **Never ask for secrets in chat.** Tell the human which `.env` variable to fill.
- **Be honest wherever a user or judge can see it.** Label real versus synthetic data, report the numbers you actually get, never invent a metric.
- **At each milestone:** commit, tick the status log at the bottom of this file, and report in at most 10 lines: what changed, what is next, any risk.

## 1. The project

**Problem.** Every new Li-ion cell goes through *formation* (its first charge/discharge cycles) and *grading* (capacity and resistance are measured and the cell is sorted into a grade). One tester runs hundreds of cells (channels) at once, each logging long voltage, current and time curves. Engineers find the bad cells by opening big exports and checking by hand or with one-off scripts. Three things hurt: every tester exports a different file layout so scripts break; faults are subtle (capacity a little low, internal resistance a little high, an odd curve shape, capacity creeping up from one cycle to the next); and a wrong call costs money both ways (a weak cell ends up in a pack, or a good cell is scrapped). The people who feel this are quality and process engineers at cell and pack makers.

**Solution.** An AI agent that takes a raw tester export and returns flagged cells with reasons, a grade for every cell, and a plain-language QC report. It (1) works out an unfamiliar file layout with no per-vendor parser, (2) plans the analysis and writes Python using NVIDIA Nemotron on Nebius Token Factory, (3) runs it in an isolated Token Factory Sandbox and repairs its own crashes, (4) uses smaller Nemotron models to explain flagged channels, (5) writes the report. **Every number comes from executed code, never from the model.**

**Why this can win.**
- Stage 1 is pass/fail on genuine track fit. Stage 2 scores four equally weighted criteria: Technological Implementation, Design (does it deliver a complete, coherent product experience rather than just a technical proof of concept), Potential Impact (a credible, specific case for a real audience), Quality of the Idea. Ties break on Technological Implementation first.
- Judges may score from the write-up and video without running anything. README, video and a free replayable demo matter as much as code.
- Organizer hints: a thin wrapper is not enough, chain tools end to end, use the biggest Nemotron for serious reasoning and smaller ones for fast, cheap calls (credits stretch further), assistants that remember across sessions are valued. Video tips: lead with the problem, say "Nebius" and "NVIDIA" aloud, name the project like a human, submit early.

## 2. Hard requirements (all must be true at submission)

- [ ] Runs on Nebius: makes a runtime call to the Token Factory inference API (or runs on AI Cloud compute) and uses at least one NVIDIA open model. Per the hackathon FAQ, calling Nemotron through Hugging Face or OpenRouter does not count, so always call Token Factory.
- [ ] Public GitHub repo with an OSS license file (**Apache-2.0**) visible at the top of the repo and in the About section. README with setup and run instructions that highlights NVIDIA Nemotron usage, where Token Factory accelerated the workflow, and any other Nebius tools used.
- [ ] Working demo URL, free and open until judging ends (Tue Dec 15, 2026, 12:00 pm PT).
- [ ] Public YouTube video under 3 minutes showing the project working. No third-party trademarks or unlicensed music.
- [ ] Text description and one track named (Best Apps & Agents).
- [ ] Written feedback on Nebius Token Factory, AI Cloud and any NVIDIA tools used. Required, and the basis of the Most Valuable Feedback prize (10 × $100). Keep `docs/NEBIUS_NVIDIA_FEEDBACK.md` from day one.
- [ ] English only. No API keys in the repo or its git history. Original work solely owned by the entrants; third-party data and SDKs used within their terms.
- [ ] Optional bonus: Best Use of Tavily ($3,000) needs a functional runtime Tavily API call. A project wins one overall award, or one track award plus one bonus award.

## 3. Product spec

### 3.1 Domain primer (guidance: validate against real data, ask Akshit when unsure)

- **Formation:** first controlled charge/discharge cycles after assembly, usually at low C-rate. First-cycle capacity and coulombic efficiency (CE) are quality signals. **Grading:** capacity (and often resistance, OCV, self-discharge) is measured and cells are sorted into bins for pack matching.
- **Tester export:** per-channel time series (time, voltage, current, step or cycle id, sometimes capacity, energy, temperature). Hundreds of channels per tester. Layouts vary: CSV with preambles, Excel with sheets per channel or group, MATLAB structs, wide versus long tables, different units and current-sign conventions.
- **Features per channel and cycle (all computed by code):** discharge and charge capacity (Ah, coulomb counting), CE, internal-resistance proxy (ΔV/ΔI at current steps or charge-to-rest transitions, when present), mid-point voltage, curve-shape metrics (dQ/dV peak position and height, or ΔQ(V) variance), capacity trend across cycles (flag upward creep), noise level, data-quality flags (flatline or dead channel, time gaps, out-of-range voltage).
- **Fault taxonomy:** `LOW_CAPACITY`, `HIGH_IR`, `CURVE_SHAPE`, `CAPACITY_CREEP_UP`, `NOISY_OR_DEAD_CHANNEL`, optionally `LOW_CE`. Detection is robust statistics inside the batch (median and MAD per feature) plus absolute sanity limits.
- **Grade bins:** A/B/C/REJECT by capacity (and IR), relative to the batch median or a user-supplied nominal. Thresholds are configurable and shown. The agent proposes thresholds with reasons, a human can override them in the UI, regrading is deterministic code with no LLM call.

### 3.2 User flow

1. Upload a tester export, or pick a bundled sample.
2. Agent inspects the file and proposes a schema mapping (columns, units, channels, cycles) with confidence. Auto-accept when validation passes, otherwise ask the user to confirm.
3. Agent plans, writes and runs code in the sandbox, and repairs failures. The user watches a live timeline.
4. Results: heatmap of all channels coloured by grade or fault, flagged list with reasons and evidence, per-channel detail with curves, editable thresholds with instant regrade.
5. Report: plain-language QC summary plus an explanation per flag, exportable (Markdown, PDF if time allows). Every number links to the run artifact (code, log) that produced it.

### 3.3 Agent rules

1. **Numbers come from executed code.** LLM roles: schema inference, planning, code writing, threshold proposals, explanations. Metrics and grades are deterministic code.
2. **Two-tier ingestion.** (a) The LLM proposes a declarative layout mapping from a small sample (delimiter, header row, sheet or struct path, column→role, units, how channels and cycles are identified). Deterministic checks validate it (plausible voltage range, monotonic time, sane units, consistent current sign, at least one channel) and a generic reader applies it. (b) If validation fails twice, the planner writes a normalizer script, runs it in the sandbox and self-repairs. Both tiers output one canonical table (parquet): `channel_id, cycle, step, time_s, voltage_v, current_a` plus optional `capacity_ah, temperature_c`.
3. **Analysis library plus custom code.** The planner composes analysis from the vetted `analysis/` package (features, anomaly rules, grading) and writes extra code only for questions the library cannot answer. Everything runs in the sandbox with network off, over sharded channel groups.
4. **LLM calls scale with flagged groups, not channels.** Rate limits make one call per channel for 512 channels too slow. Never send raw time series to a model: send schema samples, per-batch feature summaries and flagged-channel evidence.
5. **Verification.** Before a report is shown, a deterministic checker confirms every number in the narrative appears in the computed results (with tolerance) and every flag cites evidence. Failing sentences are regenerated (max 2) or dropped, and counted.
6. **Self-repair.** On a sandbox error, feed the traceback back and retry (max 3). Log every attempt.
7. **Memory.** Save validated mappings and normalizers keyed by a layout fingerprint and reuse them (re-validated) on later uploads. Save user-confirmed grade thresholds per line or tester. Show "learned formats" in the UI.
8. **Optional extras (after the core is done):** an "ask about this batch" box where the agent writes code, runs it and answers with numbers; Tavily lookups for datasheet or standard values (always show source URLs, never apply silently).

## 4. Architecture and stack

```
Browser (React)  <--REST + SSE-->  FastAPI server
                                      |
                                Orchestrator (agent loop)
                  +-------------------+-----------------------+
                  |                   |                       |
          LLM client           SandboxRunner            Verifier + run store
   (Token Factory, OpenAI-     (interface)              (claims vs results,
    compatible; planner +       |- contree  (prod)       runs/<id>/events.jsonl)
    worker models)              |- tools    (prod fallback: no free-form code)
                                |- local    (dev only, never on the public server)
```

- **Backend:** Python 3.12, FastAPI, Pydantic v2, `openai` SDK, `contree-sdk`, pandas, numpy, scipy, scikit-learn, pyarrow, h5py, openpyxl. Manage with `uv`.
- **Frontend:** React + Vite + TypeScript, canvas or SVG heatmap, SSE for the event stream. FastAPI serves the built frontend so one Docker image deploys anywhere.
- **Persistence:** files per run (`runs/<id>/`: events JSONL, canonical parquet, results JSON, report). No database.
- **Make targets:** `make setup`, `make dev`, `make test`, `make synth`, `make eval`, `make demo`.

### 4.1 Token Factory inference

- Base URL `https://api.tokenfactory.nebius.com/v1/`, key in `NEBIUS_API_KEY`, OpenAI-compatible (VERIFIED). `GET /v1/models?verbose=true` returns context length, pricing and per-request limits (VERIFIED). Save a snapshot of the live catalog (no secrets).
- NVIDIA model IDs confirmed in Nebius's own notices (VERIFIED): `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3_5-Lightning`. Likely Ultra ID from a third-party gateway listing (VERIFY): `nvidia/nemotron-3-ultra-550b-a55b`. **Retired, do not use:** `nvidia/Nemotron-3-Nano-Omni`, `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1`, `nvidia/Cosmos3-Super-Reasoner` (left serverless on Aug 31, 2026).
- Roles in `config/models.yaml`: **planner** = the largest NVIDIA model that passes your tool-calling test (Ultra if listed, else Super); **worker** = a fast NVIDIA model (Lightning if it passes). Choose at startup by intersecting with the live catalog, log the chosen IDs, compute cost from the catalog pricing.
- Function calling uses OpenAI `tools` and `tool_choice`. Each tool result goes back as a `role:"tool"` message with the matching `tool_call_id` and function `name`. The docs do not list which models support it or whether parallel calls work, so test each chosen model (VERIFY).
- Structured output uses `response_format={"type":"json_schema", ...}`. The docs are ambiguous about wrapping (bare schema versus `{name, schema, strict}`), so test both. Always validate with Pydantic and retry on failure (VERIFY).
- Rate limits are set in the dashboard. The docs' example baseline is 60 RPM and 400,000 TPM. Limits scale in 15-minute windows (+20% if usage ≥ 80%, −⅓ if ≤ 50%, up to 20×). On HTTP 429 wait for `Retry-After`; watch `x-ratelimit-remaining-requests` and `-tokens`. Use bounded concurrency (start at 4–8), backoff and caching of identical calls. A Batch API exists for bulk async work (optional) (VERIFIED).

### 4.2 Token Factory Sandboxes (Beta)

- **Access must be requested.** The profile status `inactive` means the project lacks Sandboxes permission: a human emails contree@nebius.com with the project ID and profile status (never the API key). Until access arrives, build against the `local` runner and design the `tools` fallback (VERIFIED).
- SDK: `uv add "contree-sdk==0.3.6"`; env vars `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID`; `from contree_sdk import Contree`; `client = Contree()` (VERIFIED). CLI is `contree-cli==0.9.4` with `NEBIUS_AI_PROJECT`.
- Calls shown in the docs (VERIFIED unless noted): `image = await client.images.oci("docker.io/library/python:3.12")` (VERIFY this call and image name; the quickstart itself uses `client.images.use("alpine:3.19", strict=True)`); `run = await image.run(shell=..., files={"/in/data.parquet": path_or_bytes}, disposable=False, timeout=...)`; results expose `.exit_code .stdout .stderr .uuid`; `await run.download("/out/results.json", Path(...))` needs `disposable=False`; `client.images.use(uuid, strict=True)` restarts from a saved image.
- **Prepare once, reuse:** install `numpy pandas scipy scikit-learn pyarrow` (and the project's `analysis` package) into a python image with network on, save the image UUID, start every analysis run from that UUID with network off.
- Networking is on by default. The REST field `networking.enabled=false` starts the VM with no guest network interface. Find the Python SDK equivalent in the SDK reference (VERIFY). The docs describe no destination allowlist.
- Recorded stdout and stderr default to 1 MiB each (max 10 MiB with `truncate_output_at`): write results to files instead of printing them.
- Limits (VERIFIED): at most 50 simultaneous operations in Beta (stay well under with a semaphore); checkpoint images kept 180 days. **Undocumented (measure):** CPU, RAM, disk, upload size, per-operation timeout cap.
- Shard channels into groups and run groups concurrently. Track every item with a stable ID, attempt number, operation ID and result image UUID.
- Do not put secrets in sandboxes. Keep `preserve_env` false.
- Stretch: fork from the same prepared image to compare two detection strategies and keep the better branch ("Try two coding fixes and keep the passing branch" cookbook recipe).
- Docs: `/sandboxes/overview`, `/sandboxes/start/set-up-access`, `/sandboxes/start/python-quickstart`, `/sandboxes/guides/work-with-files-and-artifacts`, `/sandboxes/guides/configure-networking-and-secrets`, `/sandboxes/guides/run-concurrent-workloads`, `/sandboxes/sdk/python_sdk/reference/index`, `/sandboxes/cookbook/index`, `/sandboxes/operate/limits-retention-and-usage`.
- **`tools` fallback** (if Sandboxes access never arrives): the model picks from vetted analysis functions through function calling and the declarative ingestion mapping; no free-form code runs on the server. Say clearly in the README which mode the public demo uses.

### 4.3 Contract (freeze `contracts/` v0 by the end of Phase 1)

Suggested events (SSE, one JSON object per event): `run.started`, `schema.proposed`, `schema.validated`, `llm.call` (role, model, tokens in/out, latency, cost), `code.generated`, `sandbox.started`, `sandbox.finished` (exit code, stdout tail, artifacts), `repair.attempt`, `analysis.progress`, `results.ready`, `verify.claim_failed`, `report.ready`, `run.failed`.

Suggested endpoints: `GET /api/samples`, `POST /api/runs` (upload or sample id), `GET /api/runs/{id}/events` (SSE), `GET /api/runs/{id}/results`, `GET /api/runs/{id}/channels/{ch}`, `POST /api/runs/{id}/regrade` (thresholds), `GET /api/runs/{id}/report?format=md|pdf`, `POST /api/replay/{sample}` (stream a saved run with realistic timing), optional `POST /api/runs/{id}/ask`.

Results JSON per channel: id, per-cycle features, flags (type, severity, evidence: metric, value, batch median, robust z), grade, explanation text, provenance (run id, code hash). Ship `contracts/fixtures/sample_run.jsonl` so the UI can be built before the agent works.

### 4.4 Demo safety and budget

- The public demo must stay free and open until Dec 15, and credits are limited ($25 from the Devpost form with code `NEBIUS-DEVPOST-GLOBAL26`, plus $25 from the Nebius Builders Program, https://dev.nebius.com/builders).
- **Replay mode:** pre-recorded sample runs replay the full agent timeline with zero LLM calls. This is what judges and the video use.
- **Live mode:** per-IP rate limit, global daily budget cap, visible "live mode" banner, env-var kill switch, token and cost accounting per run.
- Uploaded files are deleted after 24 hours. The UI states that uploads are processed by Nebius services and asks users not to upload confidential data.

## 5. Data

### 5.1 Public datasets (checked Oct 17–18, 2026)

Never commit raw datasets. `scripts/fetch_data.py` downloads what a script can reach; `data/README.md` documents manual steps. Cite every dataset in the README ("Data sources and licenses") and in `THIRD_PARTY.md`.

| Dataset | What it is | Format, size | Terms seen | Use for |
|---|---|---|---|---|
| [Michigan fast-formation study](https://doi.org/10.7302/pa3f-4w30) | 40 pouch cells (NMC111/graphite, 2.36 Ah), two formation protocols, raw formation and cycling data from a Maccor cycler; the paper defines cycle life as cycles to 70% capacity | CSV, 2.37 GB; a scripted download got HTTP 403, so use a browser or Globus | No licence shown. Cite, do not re-host. | Real formation data with real lifetimes (R1, R3) |
| [MIT-Stanford cycle life](https://data.matr.io/1/) | 124 LFP/graphite cells (A123, 1.1 Ah) in 3 batches, 30 °C, cycled to 80% capacity, lives ≈150–2,300 cycles | Site needs JavaScript; file format unverified (VERIFY) | Not stated where I looked. Cite Severson et al., Nature Energy 4, 383–391 (2019). | Real batch with real lifetimes and published baselines (R3) |
| [UConn-ISU-ILCC 2025](https://digitalcommons.lib.uconn.edu/reil_datasets/1/) | 64 LFP/graphite cells, 11 test conditions, 1 Hz data, to 80% capacity | zips plus CSV and README | CC BY 4.0 | Clean real batch to plant faults in (R2) |
| [NASA PCoE Li-ion aging](https://www.nasa.gov/content/prognostics-center-of-excellence-data-set-repository) | 18650 cells at several temperatures | zip ≈210 MB: https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip (link responds) | Use at own risk; acknowledge the repository and donors | Another file style (R1) |
| [Oxford Battery Degradation Dataset 1](https://ora.ox.ac.uk/objects/uuid:03ba4b01-cfed-46d3-9b1a-7d4a7bdf6fac) | 8 Kokam 740 mAh pouch cells | one .mat, 254 MB (link responds) | ODbL 1.0: give credit, do not re-host | Another file style (R1) |
| [CALCE](https://web.calce.umd.edu/batteries/data/) | CS2, CX2, A123, K2, PL, PLN cell groups | mostly .xlsx in zips | Cite CALCE; page says all rights reserved, do not re-host | A messy Excel style (R1) |

Published reference for MIT-Stanford (RMSE in cycles; train / primary test / secondary test), as re-reported in arXiv 2101.01885: mean-of-training 327 / 399 / 511; variance model 104 / 138 / 196; discharge model 76 / 86 / 173; full model 51 / 100 / 214.

**Gap:** no public dataset has hundreds of channels from a factory formation or grading tester. The large-batch scenario is synthetic and must be labelled as such.

### 5.2 Synthetic batch generator (`synthetic/`)

- Build N channels (default 512) from real per-cell curves (UConn, MIT-Stanford) with realistic cell-to-cell spread, a formation-plus-grading protocol (for example 3 formation cycles and 1 grading cycle) and reduced time resolution so a batch stays near 200 MB or less.
- **Planted faults** (seeded, with a severity grid): low capacity (−2% to −15%), high IR (+10% to +100%), curve-shape distortion (plateau or dQ/dV peak shift), capacity creep up (monotone upward drift across cycles), noisy or dead channel (noise ×k, flatline, dropouts). Write ground truth to `labels.csv`, never visible to the agent. Also generate clean batches for false-alarm rates.
- **At least five export layouts** from the same canonical data: long CSV with a metadata preamble; wide CSV with one column per channel; Excel with one sheet per channel group; semicolon-separated CSV with decimal commas, mV and mAh, timestamps for time; flipped current sign; MATLAB `.mat`. Use neutral invented layouts, not copies of any vendor's proprietary format. Label them synthetic.
- Fully deterministic (seeds), regenerated by `make synth`.

## 6. Evaluation (`eval/`): five headline results

Everything reproducible with `make eval`. Outputs go to `results/*.csv|json|png`, and README tables are generated from them. Tag every table and chart **REAL**, **REAL + PLANTED** or **SYNTHETIC**.

- **R1 Reads unseen formats (REAL).** One file each from NASA, Oxford, CALCE, Michigan, UConn (plus MIT-Stanford once its format is resolved) and the synthetic exporters. Metric: column-role and unit mapping accuracy against hand-written answer keys (`eval/answer_keys/*.yaml`), plus correct channel and cycle counts. No per-format code in the agent path; generic helpers only.
- **R2 Planted faults (REAL cells + PLANTED).** Precision, recall and F1 per fault type and severity; false-alarm rate on clean batches. Compare with a baseline on the same features (robust z-score and Isolation Forest). If the baseline matches or beats the agent on easy faults, report it and show where the agent adds value (new formats, mixed faults, explanations).
- **R3 Grades versus real lifetimes (REAL).** On Michigan (n = 40) and MIT-Stanford, rank correlation (Spearman) between the agent's grade or score and true cycle life. The Michigan paper found an early low-SOC resistance (pulse) test predicted lifetime better than formation numbers alone, so include resistance if the files contain it. Keep claims modest for n = 40. Optionally compare with the published RMSE baselines if the agent also predicts cycle life.
- **R4 Scale and cost (SYNTHETIC).** A 512-channel batch end to end: wall-clock time, tokens, estimated cost per batch. Compare tiered (planner + worker) with planner-only, and 1 versus N concurrent sandboxes.
- **R5 Reliability (ANY).** Self-repair rate (first AI-written code failed, later attempt passed); share of sampled report numbers that match an independent recomputation; run-to-run variability on R2.

Honesty rules: report all runs, keep seeds and configs, fix splits before looking at results, keep failing cases in an appendix, never claim factory-grade accuracy (public data are lab cells, not production lines).

## 7. UI and design

- **Views:** Upload and samples; Schema review; Live run (timeline: LLM calls with model name and tokens, code blocks, sandbox output, retries, verification); Batch (heatmap, filters by fault and grade, flagged table); Channel detail (curves with evidence overlay, features, explanation, provenance link); Report (render and export); Thresholds.
- **Quality bar** (Design is a scored criterion): a complete product, not a proof of concept. Clean engineering-tool look, colourblind-safe grade palette, keyboard accessible, good empty, loading and error states, no placeholder text. Show "Powered by NVIDIA Nemotron on Nebius Token Factory" visibly and include a short "How it works" panel.
- **Replay button** on every sample so judges and the video see a full run in seconds.

## 8. Repo layout, ownership, git

```
CLAUDE.md  README.md  LICENSE(Apache-2.0)  THIRD_PARTY.md  .env.example  .gitignore
Makefile  Dockerfile  docker-compose.yml
contracts/   OpenAPI, JSON Schemas, event fixtures        (shared, contract-first)
agent/       orchestrator, llm client, tools, sandbox runners, verifier, prompts   (Akshit)
analysis/    deterministic features, anomaly rules, grading; also runs in the sandbox (Akshit)
synthetic/   generator and exporters                       (Akshit)
eval/        harness, answer keys, baselines → results/    (Akshit)
server/      FastAPI app, run store                        (shared; UI-facing endpoints: partner)
web/         React UI                                      (partner)
data/        README and fetch scripts only
results/     small committed outputs
docs/        DESIGN.md DECISIONS.md PHASE0.md NEBIUS_NVIDIA_FEEDBACK.md DEMO_SCRIPT.md DEVPOST.md
tests/
```

- The partner's strengths are unknown: ask on day one and swap `web/` and `agent/` ownership if it fits better.
- `analysis/` is a plain Python package with unit tests on synthetic fixtures (no LLM). It is the source of truth for every number.
- Trunk-based git: short-lived branches (`agent/*`, `web/*`), squash-merged PRs, `main` always runnable, pull before push, no force-push on `main`.
- CI (GitHub Actions): lint, unit tests, secret scan.

## 9. Guardrails

- **Secrets:** never commit keys; `.env` is gitignored; add a pre-commit secret scan (for example gitleaks) and the same in CI; the sandbox never receives the API key.
- **LLM-written code is untrusted:** it runs only in the sandbox (network off, time and memory limits), never in the server process. The `local` runner is for development only.
- **Uploads:** size limit, type allowlist, no path traversal, parse inside the sandbox.
- **Data and licences:** public datasets and synthetic data only. No employer, internship or proprietary data or code, and do not copy code from other repos without a compatible licence. Do not commit raw datasets. List datasets and libraries with licences in `THIRD_PARTY.md`.
- **Honesty:** real versus synthetic labels everywhere; state limitations in the README.
- **Budget:** see §4.4.

## 10. Phase 0: verify before designing (write results to `docs/PHASE0.md`)

1. Detect OS and versions of Python, Node, Docker and uv; install what is missing.
2. **Humans do the credentials:** Token Factory account and project, claim credits, create an API key, copy the project ID, fill `.env`. If Nebius billing does not support the account's country (the FAQ warns some countries are missing, with no Devpost workaround), stop and tell the humans; help is on the Nebius Discord (https://discord.gg/eXYTGhgnhK). In the same step a human requests Sandboxes access (§4.2).
3. Fetch `GET /v1/models?verbose=true`, save the snapshot, pick planner and worker, record context lengths and prices.
4. Per chosen model: plain chat, function calling (single and parallel), JSON-schema output (both wrapper styles), streaming, latency. Log oddities in the feedback doc.
5. Sandboxes smoke test: prepare the python image with the scientific stack, upload a file, run a script, download a result, disable networking, measure concurrency, upload limits, CPU and RAM. If access is not ready, continue with the `local` runner and record the date access was requested.
6. Read the dashboard rate limits and run a small concurrency test; set client concurrency.
7. Start dataset downloads (Michigan first), resolve each file's real format, write the answer keys.
8. Repo hygiene: `git init`, Apache-2.0 `LICENSE`, `.gitignore`, CI, secret scan.
9. Write `docs/DESIGN.md` (max 3 pages: architecture, contracts, risk register, phase plan, cut order, five name proposals). Risks to cover: Sandboxes access, Ultra availability, rate limits, hosting cost until Dec 15, dataset terms, MIT-Stanford file format.

## 11. Timeline (IST) and cut list

| When | Goal |
|---|---|
| Sun Oct 18 night to Mon Oct 19 | Phase 0, `DESIGN.md`, contracts v0, repo skeleton, first Nemotron call, first sandbox run |
| Tue Oct 20, by 9:30 pm | Rough end to end on one public dataset: upload, schema, sandbox, flags, text report (CLI or minimal UI). Optional: the "Will It Ship" live judges' session starts 9:30 pm IST; opting in at Zoom registration gets a project reviewed live |
| Wed Oct 21 to Fri Oct 23 | Synthetic generator and exporters, analysis library, grading, baseline, SSE API, UI core (upload, timeline, heatmap) |
| Sat Oct 24 to Sun Oct 25 | Eval harness with R1–R5, UI polish, replay mode, format memory, self-repair metrics |
| Mon Oct 26 to Tue Oct 27 | Deploy, README, feedback doc, record the video, **submit a complete version on Tue Oct 27** |
| Wed Oct 28 to Thu Oct 29 | Polish, fix, re-record if needed, final check of every §2 item |
| Fri Oct 30 | Deadline 10:30 pm IST. Never plan to use this day |

**Cut order if behind (cut first to last):** Tavily, PDF export, branch-and-compare, Nebius Serverless Endpoint deployment (use any host that stays up), "ask about this batch", dark mode, MIT-Stanford in R3 (keep Michigan). **Never cut:** honest results for R1, R2 and R4 at minimum, README, video, feedback doc, working demo URL, licence, replay mode.

## 12. Deliverables

- **README (judge-facing):** one-line pitch; 20-second explanation with screenshot or GIF; why Nemotron and Token Factory (which model does what, tiering, cost numbers); architecture diagram; results tables R1–R5 with REAL/SYNTHETIC tags; run it in at most five commands; data sources and licences; limitations; Nebius tools used (inference, Sandboxes, and a Serverless Endpoint if used); team; licence.
- **Video (under 3 min):** 0:00 problem (an engineer scrolling a 512-channel export); 0:20 upload an unfamiliar file, schema detected; 0:50 agent timeline with sandbox run and a self-repair; 1:30 heatmap, a flagged cell, evidence; 2:00 report with provenance; 2:20 results (R1–R5, labelled); 2:40 say "built on NVIDIA Nemotron and Nebius Token Factory" aloud. Use a human-sounding project name.
- **Devpost text:** problem, solution, how it was built, challenges, accomplishments with real numbers, what is next.
- **Feedback doc:** what worked, friction and bugs (with reproduction steps), docs gaps, feature requests, latency and cost observations, Sandboxes Beta notes, model-specific notes. Concrete and complete beats long.

## 13. First actions for you

1. Read this file fully, then the Token Factory docs pages listed in §4.2 and the rules page.
2. Run Phase 0 (§10). Stop and report anything blocked.
3. Write `docs/DESIGN.md` and `contracts/` v0 and commit.
4. Continue with §11, reporting at each milestone as described in §0.

## Status log (update as you go)

- [ ] Phase 0 verified, `docs/PHASE0.md` written (Oct 18: toolchain, docs, repo hygiene done; probes written, waiting on `.env` keys and Sandboxes access. Oct 19: repo moved to `C:\dev\vera`, named Vera; NASA + Oxford fetched, formats resolved, R1 answer keys written)
- [x] `docs/DESIGN.md` and `contracts/` v0 committed (Oct 18; contract freeze at end of Phase 1)
- [ ] Rough end to end on one public dataset (target Tue Oct 20, 9:30 pm IST)
- [ ] Synthetic generator and five export layouts
- [ ] Analysis library, grading, baseline
- [ ] UI core: upload, timeline, heatmap, report
- [ ] Eval R1–R5 and generated README tables
- [ ] Replay mode and budget guard
- [ ] Deployed demo URL (free and open until Dec 15)
- [ ] README, `THIRD_PARTY.md`, feedback doc complete
- [ ] Video recorded and uploaded to YouTube
- [ ] Submitted on Devpost (target Tue Oct 27; hard deadline Fri Oct 30, 10:30 pm IST)
