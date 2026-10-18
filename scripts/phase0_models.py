"""Phase 0 steps 3, 4 and 6: snapshot the live model catalog, probe every NVIDIA candidate for chat,
function calling (single + parallel), JSON-schema output (bare and wrapped), streaming and latency,
then run a small concurrency test. Writes docs/phase0/catalog.json and docs/phase0/models_probe.json.

Run: uv run python scripts/phase0_models.py [--max-models N] [--concurrency 8]
Cost: a few thousand tokens per model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "phase0"
RATE_HEADERS = ("x-ratelimit-", "retry-after")


class ColumnGuess(BaseModel):
    column: str
    role: Literal["time_s", "voltage_v", "current_a", "cycle", "step", "capacity_ah", "temperature_c", "other"]
    unit: str
    confidence: float


class MappingGuess(BaseModel):
    delimiter: str
    header_row: int
    columns: list[ColumnGuess]


SAMPLE_EXPORT = """Tester: LAB-07;Channel group: A
Start: 2026-10-01 08:00:00
Rec;Cyc;Stp;Test Time;Volts (mV);Amps (mA);mAh;Temp
1;1;1;00:00:00;3412,5;0;0,000;24,8
2;1;2;00:00:10;3501,2;1180,0;3,278;24,9
3;1;2;00:00:20;3533,9;1180,0;6,556;25,0
"""
EXPECTED_ROLES = {"Test Time": "time_s", "Volts (mV)": "voltage_v", "Amps (mA)": "current_a",
                  "Cyc": "cycle", "Stp": "step", "mAh": "capacity_ah", "Temp": "temperature_c"}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_channel_summary",
        "description": "Return computed features (capacity_ah, ir_mohm, ce) for one tester channel.",
        "parameters": {
            "type": "object",
            "properties": {"channel_id": {"type": "integer", "description": "Tester channel number"}},
            "required": ["channel_id"],
        },
    },
}]


def rate_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower().startswith(RATE_HEADERS)}


def usage(resp: Any) -> dict[str, int] | None:
    u = getattr(resp, "usage", None)
    return {"prompt": u.prompt_tokens, "completion": u.completion_tokens} if u else None


def reasoning_of(msg: Any) -> bool:
    extra = getattr(msg, "model_extra", None) or {}
    return bool(extra.get("reasoning_content") or extra.get("reasoning"))


async def timed(coro):
    t0 = time.perf_counter()
    try:
        out = await coro
        return out, round(time.perf_counter() - t0, 3), None
    except Exception as e:  # noqa: BLE001 - probe records every failure mode
        return None, round(time.perf_counter() - t0, 3), f"{type(e).__name__}: {str(e)[:400]}"


async def probe_model(client: AsyncOpenAI, model: str) -> dict[str, Any]:
    res: dict[str, Any] = {"model": model}
    chat = client.chat.completions

    # 1. Plain chat
    raw, dt, err = await timed(chat.with_raw_response.create(
        model=model, max_tokens=512,
        messages=[{"role": "user", "content": "Reply with exactly the word OK."}]))
    if raw:
        r = raw.parse()
        m = r.choices[0].message
        res["chat"] = {"ok": "OK" in (m.content or ""), "latency_s": dt, "usage": usage(r),
                       "finish_reason": r.choices[0].finish_reason, "reasoning_field": reasoning_of(m),
                       "content_head": (m.content or "")[:120], "rate_headers": rate_headers(raw.headers)}
    else:
        res["chat"] = {"ok": False, "latency_s": dt, "error": err}
        return res  # model unusable, skip the rest

    # 2a. Forced single tool call
    r, dt, err = await timed(chat.create(
        model=model, max_tokens=1024, tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "get_channel_summary"}},
        messages=[{"role": "user", "content": "Get the summary for channel 12."}]))
    calls = (r.choices[0].message.tool_calls or []) if r else []
    res["tool_forced"] = {"ok": bool(calls) and json.loads(calls[0].function.arguments).get("channel_id") == 12,
                          "latency_s": dt, "error": err, "n_calls": len(calls)}

    # 2b. Auto, two channels: parallel tool calls + round trip with role=tool messages
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a battery QC assistant. Use tools for every number."},
        {"role": "user", "content": "Compare channels 3 and 7. Call get_channel_summary for both channels."}]
    r, dt, err = await timed(chat.create(model=model, max_tokens=1024, tools=TOOLS, tool_choice="auto", messages=msgs))
    calls = (r.choices[0].message.tool_calls or []) if r else []
    entry: dict[str, Any] = {"latency_s": dt, "error": err, "n_calls_first_turn": len(calls),
                             "parallel": len(calls) >= 2}
    if calls:
        fake = {3: {"capacity_ah": 2.31, "ir_mohm": 41.2, "ce": 0.874}, 7: {"capacity_ah": 2.12, "ir_mohm": 63.9, "ce": 0.861}}
        msgs.append({"role": "assistant", "content": None, "tool_calls": [c.model_dump() for c in calls]})
        for c in calls:
            ch = json.loads(c.function.arguments).get("channel_id")
            msgs.append({"role": "tool", "tool_call_id": c.id, "name": c.function.name,
                         "content": json.dumps(fake.get(ch, {"error": "unknown channel"}))})
        r2, dt2, err2 = await timed(chat.create(model=model, max_tokens=1024, tools=TOOLS, messages=msgs))
        text = (r2.choices[0].message.content or "") if r2 else ""
        entry.update(round_trip_ok=bool(r2) and "63.9" in text, round_trip_latency_s=dt2, round_trip_error=err2,
                     final_head=text[:200])
    entry["ok"] = bool(calls)
    res["tool_auto"] = entry

    # 3. JSON schema, both wrapper styles, validated with Pydantic
    schema = MappingGuess.model_json_schema()
    prompt = ("Infer the layout of this battery tester export. Respond with JSON matching this schema: "
              f"{json.dumps(schema)}\n\n{SAMPLE_EXPORT}")
    for style, fmt in {
        "bare": {"type": "json_schema", "json_schema": schema},
        "wrapped": {"type": "json_schema", "json_schema": {"name": "mapping", "schema": schema, "strict": True}},
    }.items():
        r, dt, err = await timed(chat.create(model=model, max_tokens=2048, response_format=fmt,
                                             messages=[{"role": "user", "content": prompt}]))
        entry = {"latency_s": dt, "error": err}
        if r:
            content = r.choices[0].message.content or ""
            try:
                guess = MappingGuess.model_validate_json(content)
                roles = {c.column: c.role for c in guess.columns}
                hits = sum(roles.get(k) == v for k, v in EXPECTED_ROLES.items())
                entry.update(ok=True, delimiter_ok=guess.delimiter == ";", header_row=guess.header_row,
                             role_accuracy=f"{hits}/{len(EXPECTED_ROLES)}", usage=usage(r))
            except ValidationError as e:
                entry.update(ok=False, validation_error=str(e)[:300], content_head=content[:200])
        else:
            entry["ok"] = False
        res[f"json_{style}"] = entry

    # 4. Streaming: time to first token and usage chunk
    async def stream() -> dict[str, Any]:
        t0 = time.perf_counter()
        ttft, n, got_usage = None, 0, False
        s = await chat.create(model=model, max_tokens=256, stream=True, stream_options={"include_usage": True},
                              messages=[{"role": "user", "content": "Count from 1 to 20 separated by spaces."}])
        async for chunk in s:
            if chunk.usage:
                got_usage = True
            if chunk.choices:
                d = chunk.choices[0].delta
                if (d.content or (d.model_extra or {}).get("reasoning_content")) and ttft is None:
                    ttft = time.perf_counter() - t0
                n += 1
        return {"ok": n > 0, "ttft_s": round(ttft or -1, 3), "total_s": round(time.perf_counter() - t0, 3),
                "chunks": n, "usage_chunk": got_usage}

    out, _, err = await timed(stream())
    res["stream"] = out or {"ok": False, "error": err}
    res["passes_tools"] = res["tool_forced"]["ok"] and res["tool_auto"]["ok"]
    res["passes_json"] = res["json_bare"].get("ok") or res["json_wrapped"].get("ok")
    return res


async def concurrency_test(client: AsyncOpenAI, model: str, n: int) -> dict[str, Any]:
    async def one(i: int):
        t0 = time.perf_counter()
        try:
            raw = await client.chat.completions.with_raw_response.create(
                model=model, max_tokens=16, messages=[{"role": "user", "content": f"Say {i}."}])
            return 200, time.perf_counter() - t0, rate_headers(raw.headers)
        except Exception as e:  # noqa: BLE001
            return getattr(e, "status_code", type(e).__name__), time.perf_counter() - t0, {}

    t0 = time.perf_counter()
    rows = await asyncio.gather(*(one(i) for i in range(n)))
    lat = sorted(r[1] for r in rows)
    return {"model": model, "n": n, "wall_s": round(time.perf_counter() - t0, 2),
            "statuses": [r[0] for r in rows], "p50_s": round(lat[len(lat) // 2], 2), "max_s": round(lat[-1], 2),
            "last_rate_headers": next((r[2] for r in reversed(rows) if r[2]), {})}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-models", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        print("NEBIUS_API_KEY is empty. Fill it in .env (see .env.example) and re-run.")
        return 2
    base = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
    OUT.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(f"{base.rstrip('/')}/models", params={"verbose": "true"},
                           headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        print(f"GET /models failed: HTTP {r.status_code} {r.text[:300]}")
        return 1
    catalog = r.json()
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (OUT / "catalog.json").write_text(json.dumps({"fetched_at": stamp, **catalog}, indent=2), encoding="utf-8")
    ids = [m["id"] for m in catalog.get("data", [])]
    nvidia = [m for m in catalog["data"] if m["id"].lower().startswith("nvidia/")]
    print(f"Catalog: {len(ids)} models, {len(nvidia)} NVIDIA. Saved docs/phase0/catalog.json")
    for m in nvidia:
        extra = {k: m.get(k) for k in m if k not in {"id", "object", "owned_by", "created"}}
        print(f"  {m['id']}: {json.dumps(extra)[:300]}")

    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    retired = set(cfg.get("retired", []))
    wanted = list(dict.fromkeys(cfg["planner"] + cfg["worker"] + [m["id"] for m in nvidia]))
    candidates = [m for m in wanted if m in ids and m not in retired][: args.max_models]
    missing = [m for m in cfg["planner"] + cfg["worker"] if m not in ids]
    if missing:
        print(f"Configured but not in catalog: {missing}")

    client = AsyncOpenAI(base_url=base, api_key=key, max_retries=2, timeout=180)
    results = []
    for model in candidates:
        print(f"\nProbing {model} ...", flush=True)
        res = await probe_model(client, model)
        results.append(res)
        print(json.dumps(res, indent=1)[:2500])

    def pick(role: str) -> str | None:
        ok = {r["model"] for r in results if r.get("passes_tools") and r.get("passes_json")}
        return next((m for m in cfg[role] if m in ok), None)

    chosen = {"planner": pick("planner"), "worker": pick("worker")}
    conc = await concurrency_test(client, chosen["worker"] or candidates[0], args.concurrency) if candidates else None
    report = {"run_at": stamp, "candidates": candidates, "missing_from_catalog": missing,
              "chosen": chosen, "results": results, "concurrency": conc}
    (OUT / "models_probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nChosen: {chosen}\nConcurrency: {json.dumps(conc)[:600]}\nWrote docs/phase0/models_probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
