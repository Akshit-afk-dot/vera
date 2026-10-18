"""Export contracts/models.py to contracts/schemas/*.schema.json. `--check` fails if they are stale (CI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from contracts import models as m  # noqa: E402

TARGETS = {
    "event": TypeAdapter(m.Event),
    "batch_results": m.BatchResults,
    "layout_mapping": m.LayoutMapping,
    "grade_thresholds": m.GradeThresholds,
    "canonical_row": m.CanonicalRow,
    "sample_info": m.SampleInfo,
    "run_created": m.RunCreated,
    "regrade_request": m.RegradeRequest,
    "api_error": m.ApiError,
}


def render(target) -> str:
    schema = target.json_schema() if isinstance(target, TypeAdapter) else target.model_json_schema()
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "x-contract-version": m.CONTRACT_VERSION, **schema}
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    out = ROOT / "contracts" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, target in TARGETS.items():
        path, text = out / f"{name}.schema.json", render(target)
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        print(f"Stale schemas {stale}: run `uv run python scripts/export_contracts.py` and commit.")
        return 1
    print("contracts/schemas up to date" if "--check" in sys.argv else f"wrote {len(TARGETS)} schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
