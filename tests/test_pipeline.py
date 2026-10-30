"""End-to-end run with a scripted model: unit bug -> validation -> repair; a wrong number -> verifier; then memory."""

import json
import re

import pytest

from agent.llm import ScriptedLLM
from agent.pipeline import Run
from agent.sandbox.runner import LocalRunner
from synthetic.generate import build_batch, export_long_semicolon

GOOD = '''```python
import pandas as pd
import vera_helpers as vh

def normalize(path):
    df = pd.read_csv(path, sep=";", decimal=",", skiprows=3)
    return pd.DataFrame({"channel_id": df["Chan"].astype(str), "cycle": df["Cyc"], "step": df["Stp"],
                         "time_s": vh.hhmmss_to_seconds(df["Test Time"]).to_numpy(),
                         "voltage_v": df["Volts (mV)"] / 1000, "current_a": df["Amps (mA)"] / 1000,
                         "temperature_c": df["Temp (C)"]})
```'''
BUGGY = GOOD.replace('df["Volts (mV)"] / 1000', 'df["Volts (mV)"]')  # forgets mV -> V


def responder(calls):
    def respond(role, purpose, messages):
        calls.append(purpose)
        if purpose.startswith("write normalizer"):
            return BUGGY
        if purpose.startswith("repair"):
            assert "units converted" in messages[-1]["content"]
            return GOOD
        if purpose.startswith("explain"):
            rows = json.loads(re.search(r"\(JSON\):\n(\[.*\])", messages[-1]["content"], re.S).group(1))
            return json.dumps({"explanations": {r["channel_id"]: f"{r['metric']} is {r['value']} {r['unit']} against a "
                                                f"batch median of {r['batch_median']}." for r in rows}})
        if purpose.startswith("write QC"):
            facts = json.loads(messages[-1]["content"].split("(JSON):\n", 1)[1].split("\n\nWrite", 1)[0])
            return (f"Vera graded {facts['channels_graded']} channels. The batch median capacity was 9.99 Ah. "
                    f"{facts['channels_flagged']} channels were flagged.")
        if purpose.startswith("regenerate"):
            return "The batch median capacity is shown in the grade table."
        raise AssertionError(purpose)
    return respond


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    d = tmp_path_factory.mktemp("batch")
    canon, labels = build_batch(24, seed=5, fault_rate=0.25)
    export_long_semicolon(canon, d / "export_long.csv", "t5")
    return d / "export_long.csv", labels


def test_run_repairs_verifies_and_remembers(export, tmp_path):
    path, labels = export
    calls: list[str] = []
    run = Run(path, ScriptedLLM(responder(calls)), LocalRunner(), data_label="SYNTHETIC", run_id="t1",
              runs_dir=tmp_path / "runs", memory_dir=tmp_path / "memory")
    results = run.execute()

    types = [e["type"] for e in run.events]
    assert types[0] == "run.started" and types[-1] == "run.finished"
    assert "repair.attempt" in types
    validated = [e for e in run.events if e["type"] == "schema.validated"]
    assert [v["ok"] for v in validated] == [False, True]
    assert results["summary"]["n_channels"] == 24
    flagged = {c["channel_id"] for c in results["channels"] if c["flags"]}
    planted = set(labels.loc[labels.fault != "", "channel_id"])
    assert len(flagged & planted) >= len(planted) - 2          # rules find most planted faults
    report = (tmp_path / "runs" / "t1" / "report.md").read_text(encoding="utf-8")
    assert "9.99" not in report                                 # invented number removed by the verifier
    assert run.verify_stats["claims_failed"] == 1 and run.verify_stats["sentences_regenerated"] == 1

    calls2: list[str] = []
    run2 = Run(path, ScriptedLLM(responder(calls2)), LocalRunner(), data_label="SYNTHETIC", run_id="t2",
               runs_dir=tmp_path / "runs", memory_dir=tmp_path / "memory")
    run2.execute()
    assert any(e["type"] == "memory.hit" for e in run2.events)
    assert not any(c.startswith("write normalizer") for c in calls2)   # learned format reused, no planner call
