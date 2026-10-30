"""Provider-agnostic Nemotron client (NVIDIA API Catalog or Nebius Token Factory; both OpenAI-compatible).

- Picks planner and worker models from the live catalog (config/models.yaml preferences, then a Nemotron ranking).
- Retries 429/5xx with backoff (honours Retry-After), records tokens, latency and cost per call.
- Emits one `llm.call` event per call through the `on_call` callback.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from openai import APIConnectionError, APIStatusError, OpenAI

ROOT = Path(__file__).resolve().parent.parent
THINK = re.compile(r"<think>.*?</think>", re.S)
NOT_CHAT = re.compile(r"embed|rerank|reward|guard|safety|retriev|parse|vlm|-vl\b|vision|audio|asr|tts|clip|ocr|omni", re.I)


@dataclass
class Reply:
    text: str
    model: str
    role: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float


def _size_rank(model_id: str) -> float:
    """Bigger = more capable. Uses the Nemotron tier name, then the parameter count in the ID."""
    m = model_id.lower()
    tier = 3 if "ultra" in m else 2 if "super" in m else 0.5 if ("nano" in m or "lightning" in m or "mini" in m) else 1
    params = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b(?![a-z])", m)]
    return tier * 1000 + (max(params) if params else 0)


def pick_models(available: list[str], prefs: dict[str, list[str]], retired: list[str]) -> dict[str, str]:
    avail = [a for a in available if a not in retired]
    chat = [a for a in avail if "nemotron" in a.lower() and not NOT_CHAT.search(a)]
    if not chat:
        raise RuntimeError("no Nemotron chat model in the provider catalog")
    chosen = {}
    for role in ("planner", "worker"):
        pref = next((p for p in prefs.get(role) or [] if p in avail), None)
        if pref:
            chosen[role] = pref
        else:
            ranked = sorted(chat, key=_size_rank)
            chosen[role] = ranked[-1] if role == "planner" else ranked[0]
    return chosen


class LLM:
    def __init__(self, provider: str | None = None, on_call: Callable[[Reply, str], None] | None = None,
                 models: dict[str, str] | None = None, max_retries: int = 5):
        cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
        provider = provider or os.environ.get("LLM_PROVIDER") or (
            "nvidia" if os.environ.get("NVIDIA_API_KEY") else "nebius")
        pcfg = cfg["providers"][provider]
        key = os.environ.get(pcfg["key_env"])
        if not key:
            raise RuntimeError(f"Set {pcfg['key_env']} in .env (provider '{provider}')")
        self.provider, self.base_url = provider, pcfg["base_url"]
        self.client = OpenAI(base_url=self.base_url, api_key=key, max_retries=0, timeout=300)
        self.on_call = on_call
        self.max_retries = max_retries
        self.prices: dict[str, tuple[float, float]] = {}
        available = self._catalog(key)
        self.models = models or pick_models(available, pcfg, cfg.get("retired", []))
        self.totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}

    def _catalog(self, key: str) -> list[str]:
        r = httpx.get(f"{self.base_url.rstrip('/')}/models", params={"verbose": "true"} if self.provider == "nebius" else None,
                      headers={"Authorization": f"Bearer {key}"}, timeout=60)
        r.raise_for_status()
        data = r.json().get("data", [])
        for m in data:  # Nebius verbose catalog carries per-token prices; NVIDIA's free tier has none
            p = m.get("pricing") or {}
            try:
                self.prices[m["id"]] = (float(p.get("prompt", 0)), float(p.get("completion", 0)))
            except (TypeError, ValueError):
                pass
        return [m["id"] for m in data]

    def chat(self, role: str, purpose: str, messages: list[dict[str, Any]], max_tokens: int = 4096,
             temperature: float = 0.2) -> Reply:
        model = self.models[role]
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                r = self.client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens,
                                                        temperature=temperature)
                break
            except APIStatusError as e:
                if e.status_code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise
                ra = e.response.headers.get("retry-after")
                time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else delay)
                delay = min(delay * 2, 60)
            except APIConnectionError:
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = THINK.sub("", r.choices[0].message.content or "").strip()
        u = r.usage
        tin, tout = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        pin, pout = self.prices.get(model, (0.0, 0.0))
        cost = tin * pin + tout * pout
        reply = Reply(text, model, role, tin, tout, latency_ms, round(cost, 6))
        self.totals["tokens_in"] += tin
        self.totals["tokens_out"] += tout
        self.totals["cost_usd"] += cost
        self.totals["calls"] += 1
        if self.on_call:
            self.on_call(reply, purpose)
        return reply


class ScriptedLLM:
    """Test double: `responder(role, purpose, messages) -> text`. Never used for published runs."""

    provider = "scripted"

    def __init__(self, responder: Callable[[str, str, list[dict[str, Any]]], str],
                 on_call: Callable[[Reply, str], None] | None = None):
        self.responder = responder
        self.on_call = on_call
        self.models = {"planner": "scripted-planner", "worker": "scripted-worker"}
        self.totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}

    def chat(self, role: str, purpose: str, messages: list[dict[str, Any]], **_: Any) -> Reply:
        reply = Reply(self.responder(role, purpose, messages), self.models[role], role, 100, 50, 1, 0.0)
        self.totals["calls"] += 1
        if self.on_call:
            self.on_call(reply, purpose)
        return reply


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"
