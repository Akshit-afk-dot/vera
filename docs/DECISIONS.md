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
