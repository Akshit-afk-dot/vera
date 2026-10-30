"""Deterministic side of ingestion: a layout fingerprint (for format memory) and validation of the canonical table
produced by model-written code. The model never decides whether its own output is acceptable; these checks do."""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

from agent.ingest.peek import peek, to_text

ID_LIKE = re.compile(r"[A-Za-z]{0,4}\d+")
MAX_LINE = 400


def peek_for_prompt(path) -> tuple[dict, str]:
    """Structural summary for the planner. Very wide lines are trimmed, with their field count and the first and
    last fields reported, so a 257-column export does not flood the prompt."""
    pk = peek(path)
    view = dict(pk)
    if pk.get("kind") == "text":
        delim = pk.get("sniffed_delimiter") or ","
        trimmed = []
        for ln in pk.get("first_lines", [])[:30]:
            if len(ln) > MAX_LINE:
                fields = ln.split(delim)
                ln = (f"{ln[:MAX_LINE]} ... [line has {len(fields)} fields; last 4: "
                      f"{delim.join(fields[-4:])}]")
            trimmed.append(ln)
        view["first_lines"] = trimmed
    return pk, to_text(view, 12_000)


def _norm_tokens(text: str) -> set[str]:
    toks = re.split(r"[\s,;\t|]+", text)
    return {ID_LIKE.sub("#", t).lower() for t in toks if t and not re.fullmatch(r"[-+]?[\d.,:]+", t)}


def fingerprint(peek: dict) -> str:
    """Stable across batches of the same layout (channel counts, batch names and numbers are normalised away)."""
    kind = peek.get("kind", "?")
    if kind == "text":
        lines = peek.get("first_lines", [])
        delim = peek.get("sniffed_delimiter") or ","
        header = max(lines, key=lambda ln: sum(1 for t in ln.split(delim) if t and not re.fullmatch(r"[-+\d.,:\s]+", t)), default="")
        sig = f"text|{delim}|" + "|".join(sorted(_norm_tokens(header)))
    elif kind == "excel":
        sheets = sorted({ID_LIKE.sub("#", s).lower() for s in peek.get("sheet_names", [])})
        heads = sorted({str(c).lower() for sh in peek.get("sheets", [])[1:3] for c in (sh.get("first_rows") or [[]])[0]})
        sig = "excel|" + "|".join(sheets) + "|" + "|".join(heads)
    elif kind == "mat":
        keys: set[str] = set()

        def walk(node, depth):
            if isinstance(node, dict) and depth < 4:
                for k, v in node.items():
                    keys.add(f"{depth}:{ID_LIKE.sub('#', str(k)).lower()}")
                    walk(v, depth + 1)
                    if isinstance(v, dict) and "variants" in v:
                        for var in v["variants"]:
                            walk(var.get("example", {}), depth + 1)
        walk(peek.get("tree", {}), 0)
        sig = "mat|" + "|".join(sorted(keys))
    else:
        sig = kind
    return hashlib.sha1(sig.encode()).hexdigest()[:12]


def validate(df: pd.DataFrame) -> tuple[list[dict], dict]:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    n_ch = int(df.channel_id.nunique()) if len(df) else 0
    check("at least one channel", n_ch >= 1, f"{n_ch} channels, {len(df)} rows")
    if not n_ch:
        return checks, {"n_channels": 0, "n_cycles": 0, "n_rows": 0}

    vmax, imax = float(df.voltage_v.abs().max()), float(df.current_a.abs().max())
    check("units converted (V, A)", vmax < 6 and imax < 200,
          f"max |V| {vmax:.3g}, max |I| {imax:.3g}" + (" (looks like mV/mA left unconverted)" if vmax >= 6 or imax >= 200 else ""))

    g = df.groupby("channel_id", sort=False)
    live = g.current_a.apply(lambda s: (s.abs() > 1e-3).any())
    med_v = g.voltage_v.median()[live]
    plausible = ((med_v > 1.5) & (med_v < 4.8)).mean() if len(med_v) else 0.0
    check("plausible cell voltage", plausible >= 0.9, f"{plausible:.0%} of active channels have median V in 1.5-4.8 V")

    backwards = g.time_s.apply(lambda s: float((np.diff(s.to_numpy()) < 0).mean()) if len(s) > 1 else 0.0)
    worst = float(backwards.max())
    check("time increases within each channel", worst <= 0.001,
          f"worst channel has {worst:.2%} backward time steps" + ("" if worst <= 0.001 else " (sort by time or rebuild cumulative time)"))

    corr_votes = []
    for _, s in list(g)[:24]:
        i, v = s.current_a.to_numpy(), s.voltage_v.to_numpy()
        dv = np.diff(v)
        m = (np.abs(i[1:]) > 0.02 * max(np.abs(i).max(), 1e-9)) & (np.abs(dv) > 1e-4)
        if m.sum() > 20:
            corr_votes.append(np.mean(np.sign(i[1:][m]) == np.sign(dv[m])))
    agree = float(np.median(corr_votes)) if corr_votes else None
    check("current sign: positive = charge", agree is None or agree >= 0.6,
          "no current steps to check" if agree is None else
          f"voltage moves with current sign in {agree:.0%} of samples" + ("" if agree >= 0.6 else "; current looks inverted, multiply current by -1"))

    cyc = g.cycle.nunique()
    check("cycles labelled", int(df.cycle.min()) >= 0 and int(cyc.max()) >= 1,
          f"{int(cyc.min())}-{int(cyc.max())} cycles per channel")
    stats = {"n_channels": n_ch, "n_cycles": int(cyc.max()), "n_rows": int(len(df))}
    return checks, stats
