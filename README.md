# Vera: the cell QC agent that shows its work

Vera is an AI agent that reads a raw Li-ion formation/grading tester export in any layout, grades every cell, flags the bad
ones with evidence and writes a plain-language QC report. Every number comes from code executed in an isolated
Nebius Token Factory Sandbox, never from the model. Built on **NVIDIA Nemotron** models served by
**Nebius Token Factory** for the Nebius × NVIDIA Global AI Hackathon (track: Best Apps & Agents).

> **Status: under construction (Phase 0, Oct 18, 2026).** Nothing below is a result yet. The judge-facing README
> (results R1–R5, demo link, video) replaces this before submission.

## Run the checks

```bash
uv sync
uv run pytest -q
uv run python scripts/tasks.py phase0   # needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID in .env (see .env.example)
```

`make <target>` works too where `make` is installed (`setup`, `test`, `lint`, `contracts`, `phase0`, `secrets`).

## Where things are

- `CLAUDE.md`: the full brief. `docs/DESIGN.md`: architecture, risks and plan. `docs/DECISIONS.md`: decision log.
- `contracts/`: API and event contract (Pydantic → JSON Schema) plus synthetic UI fixtures.
- `analysis/`: deterministic statistics, flag rules and grading (the source of truth for every number).
- `agent/sandbox/contree_rest.py`: Sandboxes REST client (network-off runs).

## Licence

Apache-2.0 (see `LICENSE`). Third-party software, models and datasets: `THIRD_PARTY.md`.
