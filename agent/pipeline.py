"""One Vera run: unfamiliar tester export in, graded and explained batch out.

peek (code) -> format memory -> planner writes normalize() -> sandbox -> deterministic checks -> repair (<=3)
-> features, flags, grades (code) -> worker explains flags and writes the narrative -> verifier -> report.
Every event is validated against contracts.models.Event and appended to runs/<id>/events.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import TypeAdapter

from agent import prompts
from agent.ingest.checks import fingerprint, peek_for_prompt, validate
from agent.llm import extract_code
from agent.verify import bad_numbers, facts_from, split_sentences, with_percentages
from analysis.features import channel_features
from analysis.grading import grade_channel, reference_capacity
from analysis.rules import detect
from contracts.models import BatchResults, Event, GradeThresholds

ROOT = Path(__file__).resolve().parent.parent
MAX_ATTEMPTS = 4  # first try + 3 repairs
EVENT = TypeAdapter(Event)
FEATURES_FOR_RULES = ["capacity_ah", "ir_mohm", "first_cycle_ce", "curve_dist_pct", "capacity_slope_pct_per_cycle", "noise_mv"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _positions(ids: list[str]) -> dict[str, tuple[int, int]]:
    m = [re.fullmatch(r"([A-Za-z])(\d{1,3})", i) for i in ids]
    if all(m):
        return {i: (ord(x.group(1).upper()) - 65, int(x.group(2)) - 1) for i, x in zip(ids, m, strict=True)}
    cols = max(1, int(np.ceil(np.sqrt(len(ids)))))
    return {i: divmod(k, cols) for k, i in enumerate(ids)}


def _clean(x):
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


class Run:
    def __init__(self, input_path: Path, llm, runner, *, data_label: str, display_name: str | None = None,
                 run_id: str | None = None, mode: str = "live", runs_dir: Path = ROOT / "runs",
                 memory_dir: Path = ROOT / "memory", thresholds: GradeThresholds | None = None, use_memory: bool = True):
        self.input = Path(input_path)
        self.llm, self.runner = llm, runner
        self.data_label, self.mode = data_label, mode
        self.name = display_name or self.input.name
        self.run_id = run_id or f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', self.input.stem.lower())[:24]}"
        self.dir = runs_dir / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "code").mkdir(exist_ok=True)
        self.memory_dir = memory_dir
        self.use_memory = use_memory
        self.thresholds = thresholds or GradeThresholds()
        self.events: list[dict] = []
        self.t_start = time.perf_counter()
        self.code_seq = 0
        self.verify_stats = {"claims_checked": 0, "claims_failed": 0, "sentences_regenerated": 0, "sentences_dropped": 0}
        if hasattr(llm, "on_call"):
            llm.on_call = self._on_llm_call

    # ------------------------------------------------------------------ events
    def emit(self, type_: str, **body) -> dict:
        ev = {"v": 0, "run_id": self.run_id, "seq": len(self.events), "ts": datetime.now(UTC).isoformat(),
              "type": type_, **body}
        EVENT.validate_python(ev)  # contract check on every event
        self.events.append(ev)
        with (self.dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, default=_clean) + "\n")
        print(f"[{ev['seq']:>3}] {type_:<22} {self._summary(ev)}", flush=True)
        return ev

    @staticmethod
    def _summary(ev: dict) -> str:
        keys = ("purpose", "model", "ok", "exit_code", "attempt", "error_summary", "done", "total", "action", "reason")
        return " ".join(f"{k}={str(ev[k])[:70]}" for k in keys if k in ev)

    def _on_llm_call(self, reply, purpose: str) -> None:
        self.emit("llm.call", role=reply.role, model=reply.model, purpose=purpose, tokens_in=reply.tokens_in,
                  tokens_out=reply.tokens_out, latency_ms=reply.latency_ms, cost_usd=reply.cost_usd)

    # ------------------------------------------------------------------ main
    def execute(self) -> dict:
        try:
            return self._execute()
        except Exception as e:
            self.emit("run.failed", stage=getattr(self, "stage", "unknown"), error=f"{type(e).__name__}: {e}"[:2000])
            raise

    def _execute(self) -> dict:
        raw = self.input.read_bytes()
        self.stage = "start"
        self.emit("run.started", source={"kind": "upload", "name": self.name, "size_bytes": len(raw), "sha256": _sha(raw),
                                         "data_label": self.data_label},
                  mode=self.mode, runner=self.runner.name, models=self.llm.models, provider=self.llm.provider)
        canon, code_id = self._ingest()
        self.stage = "analysis"
        results, curves = self._analyse(canon, code_id)
        self.stage = "explain"
        self._explain(results)
        self.stage = "report"
        report = self._report(results)
        (self.dir / "results.json").write_text(json.dumps(results, indent=1, default=_clean), encoding="utf-8", newline="\n")
        (self.dir / "curves.json").write_text(json.dumps(curves, separators=(",", ":")), encoding="utf-8", newline="\n")
        (self.dir / "report.md").write_text(report, encoding="utf-8", newline="\n")
        BatchResults.model_validate(json.loads((self.dir / "results.json").read_text(encoding="utf-8")))
        self.emit("report.ready", formats=["md"])
        t = self.llm.totals
        self.emit("run.finished", duration_s=round(time.perf_counter() - self.t_start, 2), tokens_in=t["tokens_in"],
                  tokens_out=t["tokens_out"], cost_usd=round(t["cost_usd"], 6))
        return results

    # ------------------------------------------------------------------ ingestion with self-repair
    def _ingest(self) -> tuple[pd.DataFrame, str]:
        self.stage = "ingest"
        pk, peek_text = peek_for_prompt(self.input)
        fp = fingerprint(pk)
        mem = self.memory_dir / "formats" / f"{fp}.json"
        if self.use_memory and mem.exists():
            saved = json.loads(mem.read_text(encoding="utf-8"))
            self.emit("memory.hit", kind="normalizer", fingerprint=fp, saved_at=saved["saved_at"])
            canon, code_id, problem = self._try_code(saved["code"], attempt=1, source="memory")
            if canon is not None:
                return canon, code_id
        messages = [{"role": "system", "content": prompts.PLANNER_SYSTEM},
                    {"role": "user", "content": prompts.normalizer_prompt(self.input.name, peek_text)}]
        code, last_id = None, None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            purpose = "write normalizer for unfamiliar file" if attempt == 1 else "repair normalizer from failure"
            reply = self.llm.chat("planner", purpose, messages, max_tokens=6000)
            code = extract_code(reply.text)
            canon, last_id, problem = self._try_code(code, attempt)
            if canon is not None:
                self._remember(mem, fp, code)
                return canon, last_id
            if attempt < MAX_ATTEMPTS:
                self.emit("repair.attempt", attempt=attempt, max_attempts=MAX_ATTEMPTS - 1, failed_code_id=last_id,
                          error_summary=problem.strip().splitlines()[-1][:300] if problem.strip() else "unknown")
                messages += [{"role": "assistant", "content": f"```python\n{code}```"},
                             {"role": "user", "content": prompts.repair_prompt(code, problem[-5000:])}]
        raise RuntimeError(f"ingestion failed after {MAX_ATTEMPTS} attempts")

    def _try_code(self, code: str, attempt: int, source: str = "planner") -> tuple[pd.DataFrame | None, str, str]:
        self.code_seq += 1
        code_id = f"c{self.code_seq}"
        (self.dir / "code" / f"{code_id}.py").write_text(code, encoding="utf-8", newline="\n")
        self.emit("code.generated", code_id=code_id, purpose="normalize export to canonical table"
                  + (" (from format memory)" if source == "memory" else ""), attempt=attempt, sha256=_sha(code.encode()), code=code)
        self.emit("schema.proposed", tier="normalizer", attempt=attempt, code_id=code_id)
        self.emit("sandbox.started", runner=self.runner.name, code_id=code_id, shard=0, n_shards=1, channels=[])
        job = self.runner.run_normalizer(code, self.input, self.dir / "work")
        (self.dir / "code" / f"{code_id}.log").write_text(job.stdout + "\n--- stderr ---\n" + job.stderr, encoding="utf-8")
        self.emit("sandbox.finished", code_id=code_id, shard=0, ok=job.ok, exit_code=job.exit_code,
                  duration_s=round(job.duration_s, 2), stdout_tail=job.stdout[-600:], stderr_tail=job.stderr[-1500:],
                  artifacts=[f"code/{code_id}.py", f"code/{code_id}.log"], operation_id=job.operation_id)
        if not job.ok:
            return None, code_id, job.stderr or f"exit code {job.exit_code}"
        canon = pd.read_parquet(job.output)
        checks, stats = validate(canon)
        ok = all(c["ok"] for c in checks)
        self.emit("schema.validated", ok=ok, checks=checks, **stats)
        if not ok:
            failed = "\n".join(f"- {c['name']}: {c['detail']}" for c in checks if not c["ok"])
            return None, code_id, f"The code ran but the output failed validation:\n{failed}"
        return canon, code_id, ""

    def _remember(self, path: Path, fp: str, code: str) -> None:
        if not self.use_memory:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fingerprint": fp, "code": code, "saved_at": datetime.now(UTC).isoformat(),
                                    "learned_from": self.name}, indent=1), encoding="utf-8")

    # ------------------------------------------------------------------ analysis (deterministic)
    def _analyse(self, canon: pd.DataFrame, code_id: str) -> tuple[dict, dict]:
        feats, cycles, curves = channel_features(canon)
        ids = list(feats.index)
        self.emit("analysis.progress", done=len(ids), total=len(ids), unit="channels")
        flags = detect(ids, {k: feats[k].tolist() for k in FEATURES_FOR_RULES if k in feats})
        th = self.thresholds
        ref = reference_capacity(feats.capacity_ah.tolist(), th.basis, th.nominal_capacity_ah)
        live_ir = feats.ir_mohm[[not any(f["type"] == "NOISY_OR_DEAD_CHANNEL" for f in flags[c]) for c in ids]].dropna()
        med_ir = float(live_ir.median()) if len(live_ir) else None
        th_dump = th.model_dump()
        if th.source == "default":
            th_dump["rationale"] = (f"Default bins against the batch median capacity ({ref:.4g} Ah): A >= 98%, B >= 95%, "
                                    "C >= 90%; resistance limits relative to the batch median. Editable in the UI.")
        self.emit("thresholds.proposed", thresholds=th_dump)
        pos = _positions(ids)
        code_sha = _sha((self.dir / "code" / f"{code_id}.py").read_bytes())
        channels = []
        for cid in ids:
            f = feats.loc[cid]
            g = grade_channel(_clean(f.capacity_ah), _clean(f.ir_mohm), flags[cid], reference_capacity_ah=ref,
                              median_ir_mohm=med_ir, capacity_min_pct=th.capacity_min_pct, ir_max_pct=th.ir_max_pct,
                              reject_on_flags=th.reject_on_flags, max_grade_by_severity=th.max_grade_by_severity)
            noise, peak = _clean(f.noise_mv), _clean(f.dqdv_peak_v)
            cyc_rows = [{**{k: _clean(v) for k, v in r.items()}, "noise_mv": noise if r is cycles[cid][-1] else None,
                         "dqdv_peak_v": peak if r is cycles[cid][-1] else None} for r in cycles[cid]]
            channels.append({"channel_id": cid, "position": pos[cid], "grade": g, "capacity_ah": _clean(f.capacity_ah),
                             "ir_mohm": _clean(f.ir_mohm), "cycles": cyc_rows, "flags": flags[cid], "explanation": None,
                             "provenance": {"run_id": self.run_id, "code_ids": [code_id], "code_sha256": code_sha,
                                            "artifacts": [f"code/{code_id}.py", "analysis/features.py", "analysis/rules.py"]}})
        grade_counts = {k: sum(c["grade"] == k for c in channels) for k in ("A", "B", "C", "REJECT")}
        flag_counts: dict[str, int] = {}
        for c in channels:
            for fl in c["flags"]:
                flag_counts[fl["type"]] = flag_counts.get(fl["type"], 0) + 1
        summary = {"n_channels": len(channels), "n_flagged": sum(bool(c["flags"]) for c in channels),
                   "grade_counts": grade_counts, "flag_counts": flag_counts, "reference_capacity_ah": round(ref, 5),
                   "median_ir_mohm": round(med_ir, 4) if med_ir is not None else None}
        self.emit("results.ready", summary=summary)
        results = {"v": 0, "run_id": self.run_id, "data_label": self.data_label, "source_name": self.name, "mapping": None,
                   "thresholds": th_dump, "summary": summary, "channels": channels}
        self.features_table = feats
        return results, curves

    # ------------------------------------------------------------------ worker + verifier
    def _verified(self, text: str, facts: set[float], ids: list[str], fix_facts: dict) -> str:
        kept = []
        for s in split_sentences(text):
            self.verify_stats["claims_checked"] += 1
            bad = bad_numbers(s, facts, ids)
            if not bad:
                kept.append(s)
                continue
            self.verify_stats["claims_failed"] += 1
            fixed = self.llm.chat("worker", "regenerate sentence that failed verification",
                                  [{"role": "system", "content": prompts.WORKER_SYSTEM},
                                   {"role": "user", "content": prompts.fix_sentence_prompt(s, bad, fix_facts)}],
                                  max_tokens=400).text.strip()
            still = bad_numbers(fixed, facts, ids)
            action = "dropped" if still else "regenerated"
            self.emit("verify.claim_failed", sentence=s[:500], claim=", ".join(bad), action=action,
                      reason="number not found in computed results")
            if still:
                self.verify_stats["sentences_dropped"] += 1
            else:
                self.verify_stats["sentences_regenerated"] += 1
                kept.append(fixed)
        return " ".join(kept)

    def _explain(self, results: dict) -> None:
        ids = [c["channel_id"] for c in results["channels"]]
        by_type: dict[str, list[dict]] = {}
        for c in results["channels"]:
            for f in c["flags"]:
                by_type.setdefault(f["type"], []).append({"channel_id": c["channel_id"], "grade": c["grade"], **f["evidence"][0]})
        explained: dict[str, list[str]] = {}
        for fault, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            rows = sorted(rows, key=lambda r: -abs(r["robust_z"] or 99))[:12]
            reply = self.llm.chat("worker", f"explain {fault} flags",
                                  [{"role": "system", "content": prompts.WORKER_SYSTEM},
                                   {"role": "user", "content": prompts.explain_prompt(fault, rows)}], max_tokens=1500)
            m = re.search(r"\{.*\}", reply.text, re.S)
            try:
                parsed = json.loads(m.group(0))["explanations"] if m else {}
            except (json.JSONDecodeError, KeyError, TypeError):
                parsed = {}
            for r in rows:
                txt = parsed.get(r["channel_id"])
                if isinstance(txt, str) and txt.strip():
                    facts = with_percentages(facts_from(r), [])
                    ok_txt = self._verified(txt.strip(), facts, ids, r)
                    if ok_txt:
                        explained.setdefault(r["channel_id"], []).append(ok_txt)
        for c in results["channels"]:
            c["explanation"] = " ".join(explained.get(c["channel_id"], [])) or None
        s = results["summary"]
        notable = sorted((c for c in results["channels"] if c["flags"]),
                         key=lambda c: -max(abs(f["evidence"][0]["robust_z"] or 99) for f in c["flags"]))[:6]
        self.narrative_facts = {
            "channels_graded": s["n_channels"], "channels_flagged": s["n_flagged"], "grade_counts": s["grade_counts"],
            "flag_counts": s["flag_counts"], "reference_capacity_ah": round(s["reference_capacity_ah"], 3),
            "median_ir_mohm": round(s["median_ir_mohm"], 2) if s["median_ir_mohm"] else None,
            "data_label": results["data_label"],
            "most_important_channels": [{"channel_id": c["channel_id"], "grade": c["grade"],
                                         "flags": [{"type": f["type"], **{k: f["evidence"][0][k] for k in ("metric", "value", "unit", "batch_median")}}
                                                   for f in c["flags"]]} for c in notable]}
        reply = self.llm.chat("worker", "write QC report summary",
                              [{"role": "system", "content": prompts.WORKER_SYSTEM},
                               {"role": "user", "content": prompts.narrative_prompt(self.narrative_facts)}], max_tokens=1200)
        facts = with_percentages(facts_from(self.narrative_facts), [s["n_channels"], s["n_flagged"]])
        self.narrative = self._verified(reply.text, facts, ids, self.narrative_facts)
        self.emit("verify.summary", **self.verify_stats)

    # ------------------------------------------------------------------ report (deterministic around the narrative)
    def _report(self, r: dict) -> str:
        s = r["summary"]
        lines = [f"# QC report: {r['source_name']}", "",
                 f"*Run `{r['run_id']}` · data: **{r['data_label']}** · models: planner `{self.llm.models['planner']}`, "
                 f"worker `{self.llm.models['worker']}` ({self.llm.provider}) · runner: {self.runner.name}*", "",
                 "## Summary", "", self.narrative or "_The summary was removed because it failed number verification._", "",
                 "## Grades", "", f"Reference capacity {s['reference_capacity_ah']:.4g} Ah (basis: {r['thresholds']['basis']}); "
                 f"median internal resistance {s['median_ir_mohm']:.4g} mOhm." if s["median_ir_mohm"] else "", "",
                 "| Grade | Channels |", "|---|---|", *[f"| {g} | {n} |" for g, n in s["grade_counts"].items()], "",
                 "## Flagged channels", "", "| Channel | Grade | Flag | Evidence | Explanation |", "|---|---|---|---|---|"]
        for c in r["channels"]:
            for f in c["flags"]:
                e = f["evidence"][0]
                z = f"z {e['robust_z']}" if e["robust_z"] is not None else e["threshold"]
                lines.append(f"| {c['channel_id']} | {c['grade']} | {f['type']} ({f['severity']}) | "
                             f"{e['metric']} {e['value']} {e['unit']} vs median {e['batch_median']} ({z}) | {c['explanation'] or ''} |")
        v = self.verify_stats
        lines += ["", "## How these numbers were produced", "",
                  "- The file layout was converted by model-written code that ran in an isolated runner "
                  f"(`{self.runner.name}`) and passed deterministic checks; see `code/` in this run.",
                  "- Capacities, resistance, efficiencies, flags and grades come from Vera's analysis library "
                  "(`analysis/`), never from a language model.",
                  f"- Report text was checked number by number: {v['claims_checked']} sentences checked, {v['claims_failed']} "
                  f"failed, {v['sentences_regenerated']} regenerated, {v['sentences_dropped']} dropped.", ""]
        return "\n".join(lines)
