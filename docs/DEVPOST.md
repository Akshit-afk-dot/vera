# Devpost submission text (Arbiter Hacks V1, General track)

Paste each section into the matching Devpost field. Replace nothing by hand: numbers come from `results/` (refresh
with `uv run python scripts/finish.py`) and must match the README.

**Project name:** Vera
**Tagline:** The battery-cell QC agent that shows its work.
**Track:** General
**Links:** repo https://github.com/Akshit-afk-dot/vera · demo https://akshit-afk-dot.github.io/vera/ · video: (YouTube link)

## Inspiration

Every lithium-ion cell is charged and discharged a few times right after assembly (formation), then measured and
binned (grading). One tester runs hundreds of cells at once and dumps long voltage and current logs. Quality engineers
find the bad cells by opening those exports by hand or with one-off scripts, and every tester brand exports a different
layout, so the scripts break. The faults are subtle, and a wrong call costs money in both directions: a weak cell goes
into a pack, or a good one is scrapped. We wanted a tool that can take the next unfamiliar file and still be trusted.

## What it does

Vera takes a raw tester export in any layout and returns a grade for every cell, the flagged cells with evidence, and
a plain-language QC report. NVIDIA Nemotron reads the file's structure and writes the conversion code. The code runs in
isolation, deterministic checks reject wrong units, an inverted current sign or backwards time, and the model repairs
its own code from the failure. Every capacity, resistance, efficiency, flag and grade is then computed by code. Nemotron
writes the explanations and the summary, and a verifier checks every number in that text against the computed results.
The web demo replays each run step by step: model calls, generated code, sandbox results, repairs, rejected claims,
then a tray heatmap, per-cell curves, the report, and live regrading when you change the bins.

## How we built it

- Python 3.12, pandas, numpy, scipy; a provider-agnostic Nemotron client (NVIDIA API Catalog or Nebius Token Factory,
  both OpenAI-compatible). A large Nemotron plans and writes code; a small one explains.
- A trusted wrapper runs the model-written `normalize()` in a stripped subprocess, or in Nebius Token Factory Sandboxes
  over REST with networking disabled.
- A small equivalent-circuit simulator (CC-CV charging, ohmic and polarisation resistance, first-cycle loss) generates
  128-channel batches with planted faults and exports them in four invented layouts to test the agent.
- Detection is robust statistics within each batch, with an offset-aligned Q(V) curve distance for shape faults.
- Pydantic contracts for every event; a static HTML/JS demo with no build step, hosted on GitHub Pages.
- Development was assisted by Claude Code.

## Challenges we ran into

- Real READMEs lie: the NASA files use different field names from their README, and Oxford's "seconds" are MATLAB
  day numbers. We wrote our answer keys from the files themselves.
- Our first curve-shape metric flagged high-resistance cells as shape faults, because resistance shifts the whole
  curve. Aligning curves by the best voltage offset first fixed it.
- Noisy channels produced fake resistance and shape flags; we now drop noise-sensitive flags on channels already flagged noisy.

## Accomplishments we're proud of

- On simulated 128-channel batches, Vera's rules reach F1 0.95 with 0.39% false alarms on clean batches, against F1 0.60
  for a mean/std z-score and 0.44 for an Isolation Forest on the same features (SYNTHETIC; see the caveat in the README).
- (R1, R4, R5 numbers from `results/` after the live runs.)
- No number in the report comes from the model.

## What we learned

Letting the model write code is only safe when the decision to accept that code is not the model's. Most of the work
was in the checks around the model, not the prompts.

## What's next

Validation on production tester exports, a server mode that runs uploads in Nebius Sandboxes, and statistical process
control across batches (not only within one).

## Built with

python · pandas · numpy · scipy · scikit-learn · nvidia-nemotron · nvidia-api-catalog · nebius-token-factory · pydantic · github-pages
