# Vera for Jira: Codegeist 2026 plan (deadline Dec 22, 2026, 12:00 PST)

Codegeist counts an existing project only if it is "updated or rebuilt in the Forge platform after the start of the
Submission Period" (Oct 27), with a Forge manifest and at least one Forge module. So the entry is a Forge app built on
Vera's analysis engine, not the static web demo.

## Product

A quality engineer attaches a formation/grading tester export to a Jira issue (one issue per batch). Vera, inside
Jira:

1. **Issue panel**: "Analyse attachment" → live progress → tray map coloured by grade, flagged cells with evidence,
   grade bins you can edit (instant regrade), and the verified summary.
2. **Non-conformance issues**: one click creates linked Jira issues for rejected or flagged cells, each with the
   evidence (metric, value, batch median, rule) and the explanation.
3. **Rovo agent "Vera"**: "Which cells in this batch should not ship?", "Explain cell C05", "Open NCRs for the
   rejects". Actions: analyse batch, get results, explain cell, create non-conformances.
4. **Memory**: layouts learned once (Forge storage) are reused for every later batch from the same tester.

Category: **Apps for Business Teams** (manufacturing quality). Bonus: **Best Agents (Rovo)**.

## Architecture (all Forge-hosted except the model call)

| Piece | Forge capability | Notes |
|---|---|---|
| Panel UI | `jira:issuePanel`, UI Kit | Tray grid, flagged table, regrade, NCR button |
| Rovo | `rovo:agent` + `action` modules | Actions return JSON the agent turns into answers |
| Long analysis | `consumer` + async events, `timeoutSeconds` up to 900 | Panel polls status from storage |
| State, memory | Key-Value Store (240 KiB per value) | Results: summary, per-cell grades, flagged-cell curves only |
| Jira | `requestJira` | Read attachment, post comment, create linked issues |
| Model | `permissions.external.fetch.backend: integrate.api.nvidia.com` | Nemotron via NVIDIA API Catalog (free trial); key in `forge variables --encrypt` |

**Why not Forge LLMs or Forge Containers:** both have **no free allowance** (billed per token or per vCPU-hour to the
developer), and this team has no card. Forge Functions (200,000 GB-seconds free per month), KVS and Object Store
have free monthly allowances, so the app costs $0 at hackathon scale.

**Ingestion without running model code.** Inside a customer's Jira, Vera does not execute model-written code. Nemotron
proposes a declarative layout mapping (delimiter, decimal mark, header row, column roles and units, time format,
current sign, long or wide). A deterministic TypeScript reader applies it, the same checks as the Python edition
validate it (units, plausible voltage, time order, current sign, cycles), and failed checks go back to the model for a
revised mapping (up to 3 times). This is tier 1 of the original design; the Python edition keeps code generation.

**One engine, two languages.** Features, rules and grading are ported to TypeScript (`forge-app/src/core/`), and a
parity test runs the Python and TypeScript versions on the same batch and requires the same flags and grades.

## Scope and order

1. Core port + parity tests (no Atlassian account needed).
2. Mapping reader, validation, verifier, Nemotron client, pipeline; tests with a scripted model.
3. Manifest, resolvers, issue panel, Rovo agent and actions, NCR creation.
4. Deploy to a free developer site; record a demo batch; video (under 5 minutes).

Supported in v1: delimited text exports (CSV, TSV, semicolon, decimal comma, preambles), long or wide layout.
Not in v1: Excel and MATLAB files (the Python edition reads them), and attachments over 5 MB per read.

## What a human must do

1. Create a free Atlassian developer site: https://go.atlassian.com/cloud-dev
2. Install Node.js 22 or 24 LTS (the Forge CLI does not support Node 25), then `npm install -g @forge/cli`.
3. Create an Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens) and run `forge login`
   in your own terminal; the token is typed there, never into chat.
4. Register for Codegeist on Devpost; later record the video and submit.

After step 3, Claude can run `forge register`, `forge deploy` and `forge install` from this repo.
