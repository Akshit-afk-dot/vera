"""Vera command line.

uv run python -m agent models                         # which provider and Nemotron models will be used
uv run python -m agent run <export file> --label REAL|REAL+PLANTED|SYNTHETIC [--name "..."] [--publish]
uv run python -m agent publish <run_id>               # copy a finished run into web/runs for the static demo
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WEB_RUNS = ROOT / "web" / "runs"
PUBLISHED_FILES = ("events.jsonl", "results.json", "curves.json", "report.md")


def publish(run_id: str, dev: bool = False) -> Path:
    src = ROOT / "runs" / run_id
    events = [json.loads(line) for line in (src / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    start, end = events[0], events[-1]
    if end["type"] != "run.finished":
        raise SystemExit(f"run {run_id} did not finish; not publishing")
    scripted = start.get("provider") == "scripted"
    if scripted and not dev:
        raise SystemExit("runs made with the scripted test model can only be published with --dev (never committed)")
    pub_id = f"dev-{run_id}" if dev else run_id
    dst = WEB_RUNS / pub_id
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "code").mkdir(parents=True)
    for f in PUBLISHED_FILES:
        shutil.copy(src / f, dst / f)
    for f in (src / "code").glob("*"):
        shutil.copy(f, dst / "code" / f.name)
    res = json.loads((src / "results.json").read_text(encoding="utf-8"))
    entry = {"id": pub_id, "name": res["source_name"], "data_label": res["data_label"],
             "n_channels": res["summary"]["n_channels"], "n_flagged": res["summary"]["n_flagged"],
             "grade_counts": res["summary"]["grade_counts"], "models": start["models"], "provider": start.get("provider"),
             "runner": start["runner"], "duration_s": end["duration_s"], "tokens": end["tokens_in"] + end["tokens_out"],
             "cost_usd": end["cost_usd"], "repairs": sum(e["type"] == "repair.attempt" for e in events),
             "memory_hit": any(e["type"] == "memory.hit" for e in events), "created": start["ts"]}
    index_path = WEB_RUNS / ("index.local.json" if dev else "index.json")
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    index = [e for e in index if e["id"] != pub_id] + [entry]
    index_path.write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"published {pub_id} -> {dst.relative_to(ROOT)}")
    return dst


def main() -> int:
    load_dotenv(ROOT / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models")
    r = sub.add_parser("run")
    r.add_argument("file", type=Path)
    r.add_argument("--label", required=True, choices=["REAL", "REAL+PLANTED", "SYNTHETIC"])
    r.add_argument("--name")
    r.add_argument("--run-id")
    r.add_argument("--runner", choices=["local", "contree"])
    r.add_argument("--no-memory", action="store_true")
    r.add_argument("--publish", action="store_true")
    p = sub.add_parser("publish")
    p.add_argument("run_id")
    p.add_argument("--dev", action="store_true")
    a = ap.parse_args()

    if a.cmd == "publish":
        publish(a.run_id, a.dev)
        return 0
    from agent.llm import LLM

    llm = LLM()
    if a.cmd == "models":
        print(json.dumps({"provider": llm.provider, "base_url": llm.base_url, "models": llm.models}, indent=1))
        return 0
    from agent.pipeline import Run
    from agent.sandbox.runner import make_runner

    run = Run(a.file, llm, make_runner(a.runner), data_label=a.label, display_name=a.name, run_id=a.run_id,
              use_memory=not a.no_memory)
    run.execute()
    print(f"\nrun {run.run_id}: runs/{run.run_id}/report.md")
    if a.publish:
        publish(run.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
