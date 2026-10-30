"""Trusted wrapper executed inside the sandbox (or the local dev runner).

usage: python run_job.py <input file> <output parquet>
Imports the model-written normalizer.py, calls normalize(path), coerces the canonical columns and writes parquet.
Prints one JSON line with basic stats; any exception exits 1 with the traceback on stderr (fed back for repair).
"""

import importlib.util
import json
import os
import sys
import traceback

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # vera_helpers.py sits next to this file
REQUIRED = ["channel_id", "cycle", "step", "time_s", "voltage_v", "current_a"]
OPTIONAL = ["temperature_c", "capacity_ah"]


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    spec = importlib.util.spec_from_file_location("normalizer", os.path.join(HERE, "normalizer.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        df = mod.normalize(src)
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"normalize() must return a pandas DataFrame, got {type(df).__name__}")
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise KeyError(f"normalize() output is missing required columns {missing}; got {list(df.columns)}")
        out = df[REQUIRED + [c for c in OPTIONAL if c in df.columns]].copy()
        out["channel_id"] = out["channel_id"].astype(str)
        out["cycle"] = pd.to_numeric(out["cycle"], errors="raise").astype("int64")
        out["step"] = pd.to_numeric(out["step"], errors="raise").astype("int64")
        for c in ["time_s", "voltage_v", "current_a"] + [c for c in OPTIONAL if c in out.columns]:
            out[c] = pd.to_numeric(out[c], errors="raise").astype("float64")
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        out.to_parquet(dst, index=False)
    except Exception:  # noqa: BLE001 - the traceback is the repair signal
        traceback.print_exc()
        return 1
    print(json.dumps({"rows": len(out), "channels": int(out.channel_id.nunique()),
                      "cycles_max": int(out.cycle.max()) if len(out) else 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
