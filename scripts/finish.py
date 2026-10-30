"""Finish Vera once a model key is in .env: record the live demo runs, publish them, compute R1/R4/R5,
refresh the README tables and run the tests. Safe to re-run; every step reports what it did.

uv run python scripts/finish.py                 # everything
uv run python scripts/finish.py --only real-oxford demo-s7-mat
uv run python scripts/finish.py --skip-runs     # re-score and re-publish existing runs only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

from eval.agent_stats import summarize  # noqa: E402
from eval.agent_stats import to_markdown as stats_md  # noqa: E402
from eval.formats import Case, evaluate  # noqa: E402
from eval.formats import to_markdown as formats_md  # noqa: E402

SYN = ROOT / "data" / "synthetic"
RAW = ROOT / "data" / "raw"
NASA = RAW / "nasa" / "battery_data_set" / "5. Battery Data Set"
KEYS = ROOT / "eval" / "answer_keys"
NASA_25_44 = [f"B00{n}" for n in (25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 36, 38, 39, 40, 41, 42, 43, 44)]

# run_id, input, label, display name, publish, truth for R1, extra
RUNS = [
    ("demo-s7-semicolon", SYN / "s7" / "export_long.csv", "SYNTHETIC",
     "128-channel batch · semicolon CSV, mV/mA, decimal commas", True, SYN / "s7" / "canonical.parquet", {}),
    ("demo-s7-excel", SYN / "s7" / "export_groups.xlsx", "SYNTHETIC",
     "128-channel batch · Excel, one sheet per tray row", True, SYN / "s7" / "canonical.parquet", {}),
    ("demo-s7-mat", SYN / "s7" / "export_struct.mat", "SYNTHETIC",
     "128-channel batch · MATLAB struct, discharge-positive current", True, SYN / "s7" / "canonical.parquet", {}),
    ("demo-s7-wide", SYN / "s7" / "export_wide.csv", "SYNTHETIC",
     "128-channel batch · wide CSV, no cycle or step columns", False, SYN / "s7" / "canonical.parquet", {}),
    ("demo-s8-semicolon", SYN / "s8" / "export_long.csv", "SYNTHETIC",
     "Next batch, same layout · learned format reused", True, SYN / "s8" / "canonical.parquet", {}),
    ("real-oxford", RAW / "oxford" / "Oxford_Battery_Degradation_Dataset_1.mat", "REAL",
     "Oxford Battery Degradation Dataset 1 · 8 cells", True, KEYS / "oxford.yaml", {}),
    ("real-nasa-25-44", NASA / "3. BatteryAgingARC_25-44.zip", "REAL",
     "NASA PCoE · 18 cells, zip of MATLAB files", True, KEYS / "nasa.yaml", {"channels": NASA_25_44}),
    ("r1-nasa-b0005", NASA / "1. BatteryAgingARC-FY08Q4" / "B0005.mat", "REAL",
     "NASA PCoE · B0005 (single cell)", False, KEYS / "nasa.yaml", {}),
]


def sh(*cmd: str, log: Path | None = None) -> int:
    print("+", " ".join(cmd), flush=True)
    if log is None:
        return subprocess.call(list(cmd), cwd=ROOT)
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(list(cmd), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        for line in p.stdout:
            print("   ", line.rstrip()[:160], flush=True)
            f.write(line)
        return p.wait()


def ensure_data() -> None:
    if not (SYN / "s7" / "export_struct.mat").exists():
        sh(sys.executable, "-m", "synthetic.generate", "--channels", "128", "--seed", "7", "--out", str(SYN / "s7"))
    if not (SYN / "s8" / "export_long.csv").exists():
        sh(sys.executable, "-m", "synthetic.generate", "--channels", "128", "--seed", "8", "--layouts", "long_semicolon",
           "--out", str(SYN / "s8"))
    if not (RAW / "oxford" / "Oxford_Battery_Degradation_Dataset_1.mat").exists() or not NASA.exists():
        sh(sys.executable, "scripts/fetch_data.py", "nasa", "oxford")
        sh(sys.executable, "-I", "scripts/inspect_dataset.py", "nasa", "--show", "0")


def replace_block(text: str, tag: str, body: str) -> str:
    start, end = f"<!-- {tag}:start -->", f"<!-- {tag}:end -->"
    if start not in text:
        return text
    head, rest = text.split(start, 1)
    return head + start + "\n" + body + end + rest.split(end, 1)[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--skip-runs", action="store_true")
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    if not (os.environ.get("NVIDIA_API_KEY") or os.environ.get("NEBIUS_API_KEY")):
        print("No model key. Put NVIDIA_API_KEY (build.nvidia.com) or NEBIUS_API_KEY in .env, then re-run.")
        return 2
    if sh(sys.executable, "-m", "agent", "models") != 0:
        print("Could not reach the model provider with this key; fix that first.")
        return 1
    ensure_data()
    selected = [r for r in RUNS if not a.only or r[0] in a.only]
    if not a.skip_runs:
        if not a.only:
            shutil.rmtree(ROOT / "memory" / "formats", ignore_errors=True)  # learn from scratch, so s8 shows a real memory hit
        logs = ROOT / "runs" / "_logs"
        logs.mkdir(parents=True, exist_ok=True)
        for run_id, path, label, name, *_ in selected:
            shutil.rmtree(ROOT / "runs" / run_id, ignore_errors=True)
            code = sh(sys.executable, "-m", "agent", "run", str(path), "--label", label, "--name", name, "--run-id", run_id,
                      log=logs / f"{run_id}.log")
            print(f"== {run_id}: {'ok' if code == 0 else f'FAILED (exit {code}), see runs/_logs/{run_id}.log'}\n", flush=True)

    from agent.__main__ import publish
    for run_id, *_, pub, _truth, _extra in RUNS:
        if pub and (ROOT / "runs" / run_id / "report.md").exists():
            publish(run_id)

    r1 = evaluate([Case(name, run_id, label, truth, extra=extra) for run_id, _p, label, name, _pub, truth, extra in RUNS])
    stats = summarize([r[0] for r in RUNS])
    out = ROOT / "results"
    (out / "r1_formats.json").write_text(json.dumps(r1, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "r1_formats.md").write_text(formats_md(r1), encoding="utf-8", newline="\n")
    (out / "r4_r5_runs.json").write_text(json.dumps(stats, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "r4_r5_runs.md").write_text(stats_md(stats), encoding="utf-8", newline="\n")
    data = ROOT / "web" / "data"
    data.mkdir(exist_ok=True)
    for f in ("r2_detection.json", "r1_formats.json", "r4_r5_runs.json"):
        shutil.copy(out / f, data / f.split("_")[0] + ".json")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for tag, f in (("R1", "r1_formats.md"), ("R2", "r2_detection.md"), ("R45", "r4_r5_runs.md")):
        readme = replace_block(readme, tag, (out / f).read_text(encoding="utf-8"))
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(formats_md(r1))
    print(stats_md(stats))
    code = sh(sys.executable, "-m", "pytest", "-q")
    print("\nDone. Review web/runs and README.md, then commit and push." if code == 0 else "\nTests failed; see above.")
    return code


if __name__ == "__main__":
    sys.exit(main())
