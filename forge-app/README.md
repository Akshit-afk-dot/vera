# Vera for Jira (Atlassian Forge app, Codegeist 2026 edition)

Vera inside Jira: attach a formation or grading tester export to an issue, and Vera grades every cell, flags the bad ones
with evidence, posts a verified summary and opens linked non-conformance issues. A Rovo agent ("Vera") answers questions
about the batch from the computed results.

- **Issue panel** (`jira:issuePanel`, UI Kit): pick the attachment, analyse, watch progress, see the tray map, flagged
  cells with evidence, edit grade bins (instant regrade, no model call), create NCR issues, post a summary comment.
- **Rovo agent** with four actions: analyse, get results, explain a cell, create non-conformances.
- **Background analysis** (`consumer`, up to 900 s) so large exports do not block the UI.
- **Format memory** in Forge storage: a layout learned once is reused for every later batch from the same tester.

## How it reads unfamiliar files without running model code

NVIDIA Nemotron (via the NVIDIA API Catalog) proposes a declarative layout mapping (delimiter, decimal mark, header row,
column roles and units, time format, current sign, long or wide). The TypeScript reader in `src/core/reader.ts` applies
it; `src/core/validate.ts` checks units, plausible voltage, time order, current sign and cycles; failures go back to the
model for a revised mapping (up to 3 times). No model-written code runs in your Jira.

## Same engine as the Python edition

`src/core/` is a port of Vera's Python engine (`analysis/`). `test/parity.test.ts` runs both on the same batch and
requires the same features (within rounding), flags and grades. `test/pipeline.test.ts` covers repair, number
verification, format memory and a wide export with no cycle columns.

```bash
npm install
npm test                 # parity + pipeline tests (Node 24 recommended; Node >= 23.6 runs .ts directly)
npx tsc --noEmit -p .    # type-check against the Forge packages
```

## Deploy to your own Jira (free developer site)

1. Create a free developer site: https://go.atlassian.com/cloud-dev
2. Use Node.js 22 or 24 (the Forge CLI does not support Node 25) and install the CLI: `npm install -g @forge/cli`
3. `forge login` with an Atlassian API token from https://id.atlassian.com/manage-profile/security/api-tokens
4. From this folder:

```bash
forge register                                            # writes your app id into manifest.yml
forge variables set --encrypt NVIDIA_API_KEY <your nvapi-... key>
forge deploy
forge install --site <your-site>.atlassian.net --product jira
```

Then open any issue, attach a `.csv`, `.tsv` or `.txt` export, and click **Vera cell QC**.

## Cost

Forge Functions, Key-Value Store and async events run inside Forge's free monthly allowance at this scale. The model
calls go to NVIDIA's API (free trial credits). Vera does not use Forge LLMs or Forge Containers, which have no free
allowance. Calling an external API makes the app ineligible for the "Runs on Atlassian" badge.

## Limits (v1)

Delimited text exports only (the Python edition also reads Excel and MATLAB files); one export of up to a few tens of MB
per analysis; results for up to roughly 200 channels per batch fit Forge storage limits.
