# Design (v0, Oct 18)

**Pitch.** Drop in a raw formation/grading tester export in any layout; get every cell graded, the bad ones flagged with evidence, and a QC report in which every number comes from code that ran in a Nebius sandbox.

## Name (pick one, then rename the repo)

| Name | Why |
|---|---|
| **Vera** (recommended) | Latin for "true": the product's edge is that every number is verified. "Vera, the cell QC agent that shows its work." |
| Tessa | Reads your *tester*; friendly and easy to say aloud in the video |
| Gaston | After Gaston Planté, who built the first rechargeable battery (1859) |
| Mira | "Look" in several languages; it looks at 512 channels so you don't have to |
| Otto | Short, symmetric, hints at "auto-grading" |

## Architecture

```
React (Vite, TS) ──REST+SSE── FastAPI ── Orchestrator ──┬─ LLM client (Token Factory, planner/worker, cache, cost)
                                         run store       ├─ SandboxRunner: contree (REST, network off) | tools | local(dev)
                                         memory store    └─ Verifier (claims vs fact table)
```

One Docker image: FastAPI serves the built UI. No database: `runs/<id>/` holds `events.jsonl`, `canonical.parquet`, `results.json`, `report.md` and `artifacts/` (code, logs, shard outputs). `memory/` holds learned formats and thresholds.

### Pipeline (one run)

| Stage | Who | What | LLM calls |
|---|---|---|---|
| S0 Fingerprint | code | Hash of extension, sheet names, normalised header tokens and delimiter → look up `memory/formats/` | 0 |
| S1 Sample | code (in sandbox for binary formats) | ≤40 lines, or sheet names + first rows, or `.mat` tree (keys, shapes, dtypes) | 0 |
| S2 Tier-1 mapping | **planner**, JSON schema | Proposes a `LayoutMapping`; deterministic checks (voltage range, monotonic time, current sign, ≥1 channel); one retry with the failed checks | 1–2 |
| S2b Tier-2 normalizer | **planner** + sandbox | If tier 1 fails twice: write a normalizer script, run, repair (≤3) | 0–4 |
| S3 Canonicalise | code in sandbox | Generic reader → canonical parquet, sharded by channel group | 0 |
| S4 Features | **planner** writes glue code over `analysis/`; sandbox per shard, network off | Per-channel, per-cycle features; repair on failure (≤3) | 1–4 |
| S5 Detect + grade | code (server) | Batch-level robust z over the merged feature table (robust stats need the whole batch, so shards only compute features) → flags → grades | 0 |
| S6 Thresholds | **worker**, JSON | Proposes bins with a rationale; user can override; regrade is code only | 1 |
| S7 Explain + report | **worker** | One call per flag *type* (not per channel) + one narrative call | ≤8 |
| S8 Verify | code | Every number in the narrative must match the fact table (rounding-aware, 0.5% relative); each flagged sentence must name a flagged channel. Failing sentence: regenerate ≤2, then drop; all counted | 0–4 |

About 6–20 LLM calls per run regardless of channel count, which keeps us far below the 60 RPM baseline even for 512 channels. Raw time series never go to a model.

### Models (Nemotron on Token Factory)

`config/models.yaml` lists preferences per role. At startup the agent intersects them with the live catalog and the Phase 0 probe results (tools + JSON must pass). **Planner**: Nemotron 3 Ultra if listed and passing, else Super (mapping, planning, code, repair). **Worker**: Nemotron 3.5 Lightning (thresholds, explanations, narrative). Every call emits `llm.call` with tokens, latency and cost from catalog pricing. The client has a semaphore (start at 6), backoff on 429 honouring `Retry-After`, and a disk cache keyed by (model, messages, params), which also makes `make eval` reruns cheap.

### Sandboxes

`SandboxRunner.run(code, inputs, outputs, timeout) -> RunResult`, three implementations:
- **contree** (production): image prepared once (`python:3.12-slim` + numpy/pandas/scipy/sklearn/pyarrow + our `analysis/` files) → UUID in `SANDBOX_IMAGE_UUID`. Each run: upload inputs, `POST /v1/instances` with `networking.enabled=false`, `disposable=false` only when artifacts must be downloaded, results written to files (stdout is capped at 1 MiB). At most 8 operations at once (Beta limit 50). Every operation ID and image UUID goes into the event log for provenance.
- **tools** (fallback if Sandboxes access never arrives): the planner picks vetted `analysis/` functions through function calling; the server runs only our code. The README states which mode the public demo uses.
- **local** (dev only): subprocess with timeout; refuses to start when `PUBLIC_DEPLOYMENT=1`.

Uploaded bytes are parsed only inside the sandbox (tier-1 reader included), never in the server process.

### Memory

`memory/formats/<fingerprint>.json` = validated mapping or normalizer code, first/last used, use count, source name. It is re-validated on every reuse; failure falls back to S2. `memory/thresholds/<line>.json` = user-confirmed bins. The UI shows a "Learned formats" list and emits `memory.hit` when one is reused. This is the "remembers across sessions" story.

### Replay and live

**Replay** re-emits a recorded `events.jsonl` with the original inter-event gaps (each capped at 3 s, whole run ≤ 60 s) and serves the recorded results, report and artifacts: zero LLM calls. Judges and the video use it. **Live** sits behind `LIVE_MODE_ENABLED`, a per-IP daily limit, a global daily dollar cap computed from `llm.call` costs, a visible banner, uploads deleted after 24 h, and a notice that uploads are processed by Nebius services.

### Contracts

`contracts/models.py` → `contracts/schemas/*.json` (CI checks they are current). The UI builds against `contracts/fixtures/` (a 64-channel synthetic run including one self-repair) before the agent exists. See `contracts/README.md` for events and endpoints. Freeze at the end of Phase 1; after that, changes need a version bump.

## Data honesty

Bundled demo samples are data we re-host, so they must be fully synthetic or derived only from CC BY sources (UConn), with attribution. Michigan, MIT-Stanford, CALCE and Oxford are fetched by the user's own scripts and never re-hosted. Every table and chart carries REAL / REAL+PLANTED / SYNTHETIC.

## Risk register

| # | Risk | L/I | Mitigation | Trigger to switch |
|---|---|---|---|---|
| R1 | Sandboxes access late or never | M/H | Build on `local`; `tools` runner ready by Oct 23 | No access by Thu Oct 22 → demo uses `tools`, README says so |
| R2 | Ultra not in catalog or fails tools/JSON | M/M | Super as planner; tiering story still holds (Super vs Lightning) | Probe result |
| R3 | Rate limits / 429s | L/M | Call count independent of channels; semaphore; cache; Batch API for eval | p95 latency > 30 s in probe |
| R4 | Hosting cost until Dec 15 | M/H | Replay needs CPU only; cheapest always-on host; live mode kill switch + budget cap | Decide host by Mon Oct 26 |
| R5 | Dataset terms | M/M | Never re-host restricted data; fetch scripts; synthetic from CC BY only | — |
| R6 | MIT-Stanford format unresolved | M/L | R3 runs on Michigan alone (n = 40), modest claims | Unresolved by Oct 24 → drop |
| R7 | LLM output drift (mapping, code) | M/M | Pydantic validation + retries, deterministic checks, repair loop, R5 metrics report it honestly | — |
| R8 | Repo in OneDrive (sync of `.venv`, `node_modules`, data; file locks) | H/M | Move repo to e.g. `C:\dev\` before `web/` install; `DATA_DIR` outside OneDrive | Before partner runs `npm install` |
| R9 | Schedule slip | M/H | Cut order below; submit a complete version Tue Oct 27 | Phase gate missed by > ½ day |
| R10 | Untrusted code or uploads | L/H | Sandbox only, network off, no secrets in sandbox, size/type limits, `local` runner blocked in public | — |

## Phase plan (IST)

| Phase | When | Exit criterion |
|---|---|---|
| P0 | Oct 18–19 | Probes run; planner/worker chosen; first sandbox run (or `local`); contracts v0 committed ✅ |
| P1 | Oct 19–20 | Rough end to end on one public dataset (UConn if reachable, else NASA): upload → mapping → sandbox features → flags/grades → text report, from a CLI; server skeleton streams fixture events |
| P2 | Oct 21–23 | Synthetic generator + 5 layouts; analysis library + baseline (robust z, Isolation Forest); SSE API; UI core (upload, timeline, heatmap) |
| P3 | Oct 24–25 | Eval R1–R5 → `results/`; replay mode; memory; UI polish; self-repair metrics |
| P4 | Oct 26–27 | Deploy, README, feedback doc, video; **submit Tue Oct 27** |
| P5 | Oct 28–29 | Fixes, re-record if needed, final §2 checklist. Oct 30 is buffer only |

**Parallel from now:** the partner builds `web/` against `contracts/fixtures/` and `contracts/schemas/` (generate TS types), while Akshit and Claude build `agent/`, `analysis/` and `synthetic/`.

**Cut order** (first to last): Tavily, PDF export, branch-and-compare, Nebius Serverless Endpoint deployment, "ask about this batch", dark mode, MIT-Stanford in R3. **Never cut:** honest R1, R2, R4; README; video; feedback doc; working demo URL; licence; replay mode.
