"""R4 (scale and cost) and R5 (reliability) from the event logs of finished runs. Nothing is estimated here:
every number is read from runs/<id>/events.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_stats(run_id: str) -> dict | None:
    p = ROOT / "runs" / run_id / "events.jsonl"
    if not p.exists():
        return None
    ev = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    start, end = ev[0], ev[-1]
    calls = [e for e in ev if e["type"] == "llm.call"]
    finished = [e for e in ev if e["type"] == "sandbox.finished"]
    validated = [e for e in ev if e["type"] == "schema.validated"]
    vs = next((e for e in ev if e["type"] == "verify.summary"), {})
    res = next((e for e in ev if e["type"] == "results.ready"), None)
    first_ok = bool(finished) and finished[0]["ok"] and bool(validated) and validated[0]["ok"]
    return {"run_id": run_id, "name": start["source"]["name"], "label": start["source"]["data_label"],
            "finished": end["type"] == "run.finished", "channels": res["summary"]["n_channels"] if res else None,
            "wall_s": end.get("duration_s"), "planner_calls": sum(c["role"] == "planner" for c in calls),
            "worker_calls": sum(c["role"] == "worker" for c in calls),
            "tokens": sum(c["tokens_in"] + c["tokens_out"] for c in calls), "cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
            "memory_hit": any(e["type"] == "memory.hit" for e in ev), "first_code_ok": first_ok,
            "repairs": sum(e["type"] == "repair.attempt" for e in ev),
            "sentences_checked": vs.get("claims_checked", 0), "sentences_failed": vs.get("claims_failed", 0),
            "sentences_regenerated": vs.get("sentences_regenerated", 0), "sentences_dropped": vs.get("sentences_dropped", 0),
            "models": start["models"], "provider": start.get("provider"), "runner": start["runner"]}


def summarize(run_ids: list[str]) -> dict:
    rows = [r for r in (run_stats(i) for i in run_ids) if r]
    fresh = [r for r in rows if not r["memory_hit"]]
    first_failed = [r for r in fresh if not r["first_code_ok"]]
    return {"runs": rows,
            "self_repair": {"runs_with_new_code": len(fresh), "first_code_failed": len(first_failed),
                            "recovered_by_repair": sum(r["finished"] for r in first_failed)},
            "verification": {k: sum(r[k] for r in rows) for k in ("sentences_checked", "sentences_failed",
                                                                  "sentences_regenerated", "sentences_dropped")}}


def to_markdown(s: dict) -> str:
    lines = ["| Run | Data | Channels | Wall time | Planner / worker calls | Tokens | Cost | Repairs | Learned format |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in s["runs"]:
        cost = f"${r['cost_usd']:.4f}" if r["cost_usd"] else "free tier"
        lines.append(f"| {r['name']} | {r['label']} | {r['channels'] or 'n/a'} | {r['wall_s']:.0f} s | {r['planner_calls']} / {r['worker_calls']} | "
                     f"{r['tokens']:,} | {cost} | {r['repairs']} | {'yes' if r['memory_hit'] else 'no'} |")
    sr, v = s["self_repair"], s["verification"]
    lines += ["", f"Self-repair: in {sr['runs_with_new_code']} runs where the model wrote new code, the first attempt failed in "
              f"{sr['first_code_failed']} and repair recovered {sr['recovered_by_repair']} of those.",
              f"Verification: {v['sentences_checked']} model-written sentences checked, {v['sentences_failed']} contained a number "
              f"not in the results; {v['sentences_regenerated']} were regenerated, {v['sentences_dropped']} dropped."]
    return "\n".join(lines) + "\n"
