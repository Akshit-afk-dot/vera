# Decisions

One line each: date (IST) · decision · why. Newest at the bottom.

- 2026-10-18 · Analysis sandbox runs use the Sandboxes **REST API** (`agent/sandbox/contree_rest.py`) with `networking.enabled=false`; `contree-sdk` only prepares images · SDK 0.3.6 has no networking switch (docs + installed source).
- 2026-10-18 · `scripts/tasks.py` is the task runner; `Makefile` delegates to it · no `make` on this Windows machine; one code path for both.
- 2026-10-18 · Secret scan = dependency-free `scripts/secret_scan.py` pre-commit hook (+ gitleaks if installed) and the gitleaks binary over full history in CI · gitleaks not installed locally; the binary avoids the gitleaks-action org licence question.
- 2026-10-18 · uv project with `package = false`; top-level packages (`agent`, `analysis`, …) import from the repo root · simplest layout for a 12-day build; `analysis/` gets copied into the sandbox image as plain files.
- 2026-10-18 · `analysis/` depends only on numpy/pandas/scipy (no pydantic) · it must run inside the sandbox image.
- 2026-10-18 · Contract source of truth = Pydantic models in `contracts/models.py`; JSON Schemas exported to `contracts/schemas/` and checked in CI · one definition for agent, server and web (TS types generated from the schemas).
- 2026-10-18 · Added events `memory.hit`, `schema.needs_confirmation`, `thresholds.proposed`, `verify.summary`, `run.finished` to the suggested list · the UI needs them for memory, schema review, thresholds and the cost footer.
- 2026-10-18 · `Evidence.robust_z` is nullable · absolute sanity limits (dead channel) have no meaningful z.
- 2026-10-18 · v0 grading caps flagged cells: high-severity flag → at most C, medium → at most B; `NOISY_OR_DEAD_CHANNEL` → REJECT · a cell with a strong anomaly should not ship as A. **Akshit to confirm** the domain call.
- 2026-10-18 · v0 flag rule threshold robust |z| > 3.5 (low < 5 ≤ medium < 8 ≤ high) · placeholder; R2's clean-batch false-alarm rate sets the final value. Seen: a clean channel at −2.7σ scored z = −3.56 with n = 37 because MAD under-estimates sigma in small batches.
- 2026-10-18 · Stay in Best Apps & Agents (not Coding and Agentic Engineering) · the product serves QC engineers, not developers; writing and running code is a means here, not the product.
- 2026-10-18 · Docker is not installed locally; the deploy host or CI builds the image · avoid a heavy install (WSL2) before Phase 4.
- 2026-10-18 · Raw datasets go under `DATA_DIR` (default `data/raw`, gitignored) · lets the repo stay in OneDrive while data lives outside it.
- 2026-10-19 · Project name **Vera** (Akshit) · "the cell QC agent that shows its work": verification is the differentiator.
- 2026-10-19 · Repo moved from `OneDrive\Desktop\Hackathon` to `C:\dev\vera` · OneDrive was syncing `.venv`, and would sync `node_modules` and GBs of data.
- 2026-10-19 · R1 answer keys are written from the files themselves, with README errors listed as pitfalls · both NASA and Oxford READMEs contradict their data (field names; time unit).
- 2026-10-19 · OPEN for Phase 1 (before contract freeze): extend `LayoutMapping` with record paths for nested `.mat` structs and a `derived` current source (dq/dt), or route such files to the tier-2 normalizer · NASA and Oxford cannot be expressed in v0.
- 2026-10-30 · Nebius × NVIDIA deadline missed (no key, nothing submitted). New targets: Arbiter Hacks V1 (Dec 20) and optionally Codegeist 2026 (Dec 22); see docs/HACKATHONS.md.
- 2026-10-30 · LLM layer becomes provider-agnostic (NVIDIA API Catalog or Nebius Token Factory, both OpenAI-compatible) · no card needed for NVIDIA's free tier; Nemotron stays the model.
- 2026-10-30 · Synthetic cells come from a small equivalent-circuit simulator (PCHIP OCV, R0 + R1 polarisation, CC-CV, first-cycle loss) · capacity, IR and curve shape interact as on a real line; plausibility model, not electrochemistry.
- 2026-10-30 · CURVE_SHAPE uses an offset-aligned Q(V) distance to the batch median curve instead of the dQ/dV peak · a raw peak flagged high-IR and low-capacity cells (uniform voltage shifts).
- 2026-10-30 · Positive skewed metrics (curve distance, noise) are z-scored on a log scale; flags from noise-sensitive metrics are dropped on channels already flagged noisy · fixes cross-type confusion seen in R2 (typed F1 0.85 → 0.95).
- 2026-10-30 · Keep |z| > 3.5 (pre-registered); the sweep in results/r2_detection.md shows 4.0 trades 1 point of recall for zero false alarms. Caveat stated publicly: rules were developed on the same simulator, so R2 is optimistic until real-cell validation.
- 2026-10-30 · Ingestion is model-written code from the start (no declarative tier) with a trusted wrapper doing all I/O and deterministic validation deciding acceptance · the code path is the showcase and handles every layout; a declarative mapping was redundant for the time left.
- 2026-10-30 · Features run in-process from our own library on the validated canonical table; only model-written code goes to the isolated runner · untrusted code is isolated, trusted numbers stay reproducible.
- 2026-10-30 · Web demo is static HTML/JS (no React, no build) on GitHub Pages, replaying recorded runs only · free hosting that never sleeps, zero model cost per visitor, nothing to keep alive until judging ends.
- 2026-10-30 · Browser regrading mirrors analysis/grading.py and a parity test runs both through Node on five threshold variants.
- 2026-10-30 · Structural peeks collapse repeated keys (channels, cycles) to one example plus names and fall back to compact JSON · keeps every layout's prompt complete (Oxford 12k truncated → 4.7k complete).
- 2026-10-30 · `scripts/finish.py` is the single step from "key in .env" to a finished project: live demo runs, publish, R1/R4/R5, README tables, tests.
- 2026-10-30 · Enter both Arbiter Hacks (Vera as is) and Codegeist (Vera for Jira, a Forge rebuild) · rules of both allow it; deadlines Dec 20 and Dec 22.
- 2026-10-30 · Vera for Jira uses Forge Functions + KVS + async events, and Nemotron via NVIDIA's API; not Forge LLMs or Forge Containers · those two have no free allowance and the team has no card; functions/KVS/events stay inside Forge's free tier.
- 2026-10-30 · Inside Jira the model proposes a declarative layout mapping instead of writing code · no model-written code runs in a customer's site; same deterministic validation and repair loop.
- 2026-10-30 · The engine is ported to TypeScript (forge-app/src/core) with a parity test against the Python engine on the same batch (features within rounding, identical flags and grades).
