"""UI development only: a full pipeline run on a SYNTHETIC batch with a scripted stand-in for Nemotron.
Published with --dev into gitignored web/runs/dev-*; never shown on the public demo.

uv run python scripts/dev_run.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.__main__ import publish  # noqa: E402
from agent.llm import ScriptedLLM  # noqa: E402
from agent.pipeline import Run  # noqa: E402
from agent.sandbox.runner import LocalRunner  # noqa: E402
from synthetic.generate import build_batch, export_long_semicolon  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from test_pipeline import BUGGY, GOOD  # noqa: E402


def respond(role, purpose, messages):
    if purpose.startswith("write normalizer"):
        return BUGGY
    if purpose.startswith("repair"):
        return GOOD
    if purpose.startswith("explain"):
        rows = json.loads(re.search(r"\(JSON\):\n(\[.*\])", messages[-1]["content"], re.S).group(1))
        return json.dumps({"explanations": {r["channel_id"]: f"{r['metric']} of {r['value']} {r['unit']} sits well away "
                                            f"from the batch median of {r['batch_median']} {r['unit']}; hold for review."
                                            for r in rows}})
    if purpose.startswith("write QC"):
        f = json.loads(messages[-1]["content"].split("(JSON):\n", 1)[1].split("\n\nWrite", 1)[0])
        return (f"Vera graded all {f['channels_graded']} channels of this batch and flagged {f['channels_flagged']}. "
                f"The reference capacity was {f['reference_capacity_ah']} Ah. Review the flagged channels before pack matching.")
    return "No numbers here."


def main() -> None:
    d = ROOT / "data" / "synthetic" / "dev128"
    d.mkdir(parents=True, exist_ok=True)
    canon, _ = build_batch(128, seed=7)
    export_long_semicolon(canon, d / "export_long.csv", "dev128")
    run = Run(d / "export_long.csv", ScriptedLLM(respond), LocalRunner(), data_label="SYNTHETIC",
              display_name="Dev batch, 128 channels (scripted model)", run_id="dev128", use_memory=False)
    run.execute()
    publish("dev128", dev=True)


if __name__ == "__main__":
    main()
