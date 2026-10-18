# Phase 0: verification log

Started Sun Oct 18, 2026, 23:40 IST. Steps follow CLAUDE.md §10. Status: ✅ done · ⏳ ready, waiting on a human · ❌ blocked.

| # | Step | Status | Notes |
|---|---|---|---|
| 1 | Toolchain | ✅ | See table below. Missing: Docker, make, gitleaks (decisions in DECISIONS.md) |
| 2 | Credentials, credits, Sandboxes access | ⏳ **humans** | See "What the humans need to do" |
| 3 | Model catalog snapshot, pick planner/worker | ⏳ | `scripts/phase0_models.py` written; `GET /v1/models` answers 401 without a key (checked) |
| 4 | Per-model probes (chat, tools single + parallel, JSON both styles, streaming, latency) | ⏳ | Same script; writes `docs/phase0/models_probe.json` |
| 5 | Sandboxes smoke test | ⏳ | `scripts/phase0_sandbox.py` written; REST client unit-tested against a mock |
| 6 | Rate limits + concurrency test | ⏳ | Concurrency test is in the models probe; a human reads the dashboard limits |
| 7 | Dataset downloads | ⏳ | Waiting for go-ahead (sizes below). Michigan needs a browser/Globus |
| 8 | Repo hygiene | ✅ | git, Apache-2.0, .gitignore, CI (ruff, pytest, schema check, gitleaks), pre-commit secret scan |
| 9 | DESIGN.md | ✅ | `docs/DESIGN.md` |

## 1. Toolchain (this machine)

| Tool | Version | Notes |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | Repo lives in `OneDrive\Desktop`, which OneDrive syncs (Desktop is redirected). See risk R8 in DESIGN.md |
| Python | 3.12.10 | via `uv` venv |
| uv | 0.11.2 | `uv sync` installed all deps in 40 s |
| Node / npm | 25.2.1 / 11.6.2 | for `web/` |
| git / gh | 2.52 / 2.96 | gh is logged in as `Akshit-afk-dot` |
| Docker | not installed | Not needed until deploy; the host or CI builds the image |
| make | not installed | `scripts/tasks.py` does the same; `Makefile` delegates to it |
| gitleaks | not installed | CI downloads it; local hook uses `scripts/secret_scan.py` and gitleaks if present |

## 2. What the humans need to do (blocking steps 3–6)

1. Token Factory account → project → claim credits ($25 Devpost code from the brief, $25 Builders Program).
   If billing does not support your country, stop and tell Claude; help is on the Nebius Discord.
2. Create an API key, copy the project ID, then in the repo: `cp .env.example .env` and fill
   `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID` (and `NEBIUS_AI_PROJECT` with the same ID if you use the CLI). Never paste keys in chat.
3. Request Sandboxes access at https://tokenfactory.nebius.com/sandboxes/about. To check status:
   `uv tool install "contree-cli==0.9.4"`, then `contree auth -y` and `contree auth ls`. If the status is `inactive`,
   email contree@nebius.com with the **project ID and the status only** (never the key). Record the request date here.
4. Open https://tokenfactory.nebius.com/project/rate-limits and note RPM/TPM here.
5. Then run `uv run python scripts/tasks.py phase0` (or `make phase0`), which runs both probes and writes `docs/phase0/`.

Sandboxes access requested on: _not yet_ · Rate limits seen in dashboard: _not yet_

## Verified in the docs today (Oct 18) beyond what CLAUDE.md already lists

- **Python SDK 0.3.6 cannot disable networking.** `run()` takes `env, cwd, hostname, files, timeout, disposable,
  truncate_output_at, preserve_env`; there is no network argument (checked the installed source too). The official
  "verify with networking disabled" recipe calls REST `POST /v1/instances` with `"networking": {"enabled": false}`.
  → `agent/sandbox/contree_rest.py` uses REST for every analysis run.
- REST base `https://api.tokenfactory.nebius.com/sandboxes/v1/`, headers `Authorization: Bearer` + `Project: <id>`.
  Upload: `POST /files` (octet-stream) → `{uuid}`; spawn: `POST /instances` with `files: {"/abs/path": {"uuid", "mode"}}`
  → 201 `{uuid}`; poll `GET /operations/{id}` (status `PENDING|ASSIGNED|EXECUTING` → `SUCCESS|FAILED|CANCELLED`,
  honour `Retry-After`); result in `metadata.result.{state, stdout, stderr}` (stdout may be base64); download a file
  from the result image: `GET /inspect/{image_uuid}/download?path=`; cancel: `DELETE /operations/{id}`.
- Writable layer default 12 GiB (`resources_limits.max_layer_bytes`). No CPU/RAM fields; the timeout cap is in
  `GET /v1/whoami` → `limits`. Create requests have no idempotency key.
- Rate-limit headers include `x-ratelimit-over-limit: yes` (request served above the limit at low priority: an early
  warning) and `x-ratelimit-dynamic-*` scale/usage headers. 
- Rules re-read: submission closes Oct 30 10:00 PT; judging Dec 1–15; one Overall award **or** one Track + one Bonus;
  feedback is judged on "completeness, viability, and potential impact". The Best Apps & Agents text names
  "Nemotron 3 Ultra" for serious reasoning and "Nano or Super" for fast calls, and encourages (does not require)
  Nebius Serverless Endpoints/Jobs for deployment.

## Datasets (step 7): waiting for a go-ahead to download

| Dataset | How | Size | Destination |
|---|---|---|---|
| NASA PCoE battery | script (direct S3 zip) | ≈210 MB | `$DATA_DIR/nasa/` |
| Oxford Degradation 1 | script (single .mat) | ≈254 MB | `$DATA_DIR/oxford/` |
| UConn-ISU-ILCC 2025 | script after link check | several zips | `$DATA_DIR/uconn/` |
| CALCE (one cell group) | script after link check | tens of MB | `$DATA_DIR/calce/` |
| Michigan formation | **browser or Globus** (scripted download got 403) | 2.37 GB | `$DATA_DIR/michigan/` |
| MIT-Stanford | browser (site needs JS); format unverified | ≈3 GB | `$DATA_DIR/mit/` |

Recommendation: set `DATA_DIR` to a folder outside OneDrive before downloading (several GB would otherwise sync).
