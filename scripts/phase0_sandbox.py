"""Phase 0 step 5: Sandboxes smoke test.

1. whoami: permissions and account-effective limits (tells us if Sandboxes access is active)
2. prepare a python:3.12-slim image with the scientific stack (network on, saved image), once
3. network-off analysis run over an uploaded parquet file; download the result JSON
4. measure CPU, RAM, disk inside the VM; confirm no network interface besides loopback
5. concurrency: 1 vs 4 vs 8 simultaneous short operations
Writes docs/phase0/sandbox_probe.json.

Run: uv run python scripts/phase0_sandbox.py [--skip-prepare] [--upload-mb 1,10,50]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.sandbox.contree_rest import ContreeRest  # noqa: E402

OUT = ROOT / "docs" / "phase0"
BASE_IMAGE = "docker.io/library/python:3.12-slim"  # VERIFY: OCI import path accepted by images.oci()
PIP = "pip install --no-cache-dir numpy pandas scipy scikit-learn pyarrow"

PROBE_SCRIPT = r"""
import json, os, platform, socket, time, shutil
import numpy as np, pandas as pd
out = {}
out["interfaces"] = sorted(os.listdir("/sys/class/net"))
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3); out["egress"] = "OPEN"
except OSError as e:
    out["egress"] = f"blocked ({type(e).__name__})"
df = pd.read_parquet("/in/data.parquet")
out["rows"] = len(df); out["channels"] = int(df.channel_id.nunique())
out["capacity_ah"] = df.groupby("channel_id").apply(lambda g: float(np.trapezoid(g.current_a.clip(lower=0), g.time_s) / 3600)).round(4).to_dict()
out["nproc"] = os.cpu_count()
mem = dict(l.split(":", 1) for l in open("/proc/meminfo").read().splitlines() if ":" in l)
out["mem_total"] = mem["MemTotal"].strip()
du = shutil.disk_usage("/"); out["disk_free_gb"] = round(du.free / 1e9, 2)
t = time.perf_counter(); a = np.random.rand(1500, 1500); a @ a; out["matmul_1500_s"] = round(time.perf_counter() - t, 3)
out["python"] = platform.python_version(); out["numpy"] = np.__version__; out["pandas"] = pd.__version__
os.makedirs("/out", exist_ok=True)
json.dump(out, open("/out/result.json", "w"), indent=1)
print("probe-ok")
"""


def tiny_batch() -> bytes:
    rng = np.random.default_rng(0)
    rows = []
    for ch in range(3):
        t = np.arange(0, 3600, 10.0)
        cur = np.where(t < 1800, 1.0 + 0.01 * ch, -1.0)
        v = 3.4 + 0.5 * (t / 3600) + rng.normal(0, 0.002, t.size)
        rows.append(pd.DataFrame({"channel_id": ch, "cycle": 1, "step": (t >= 1800) + 1, "time_s": t,
                                  "voltage_v": v, "current_a": cur}))
    buf = io.BytesIO()
    pd.concat(rows).to_parquet(buf, index=False)
    return buf.getvalue()


async def prepare_image() -> dict:
    from contree_sdk import Contree  # SDK is fine here: preparation needs network on

    client = Contree()
    t0 = time.perf_counter()
    base = await client.images.oci(BASE_IMAGE)
    prepared = await base.run(shell=PIP, disposable=False, timeout=900)
    info = {"base": BASE_IMAGE, "exit_code": prepared.exit_code, "uuid": prepared.uuid,
            "seconds": round(time.perf_counter() - t0, 1), "stderr_tail": (prepared.stderr or "")[-500:]}
    if prepared.exit_code != 0 or not prepared.uuid:
        raise RuntimeError(f"image preparation failed: {info}")
    return info


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prepare", action="store_true", help="use SANDBOX_IMAGE_UUID from .env")
    ap.add_argument("--upload-mb", default="1,10", help="comma-separated upload sizes to time")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if not os.environ.get("NEBIUS_API_KEY") or not os.environ.get("NEBIUS_PROJECT_ID"):
        print("Fill NEBIUS_API_KEY and NEBIUS_PROJECT_ID in .env and re-run.")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}

    async with ContreeRest() as sbx:
        r = await sbx.whoami()
        if r.status_code != 200:
            report["whoami"] = {"http": r.status_code, "body": r.text[:300]}
            (OUT / "sandbox_probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"whoami: HTTP {r.status_code}. Sandboxes access is probably not active for this project.\n"
                  "A human should email contree@nebius.com with the project ID and this status "
                  "(never the API key). Until then the agent uses SANDBOX_RUNNER=local.")
            return 3
        who = r.json()
        report["whoami"] = {"permissions": who.get("permissions"), "limits": who.get("limits")}
        print("whoami:", json.dumps(report["whoami"], indent=1))

        image = os.environ.get("SANDBOX_IMAGE_UUID") if args.skip_prepare else None
        if not image:
            report["prepare"] = await prepare_image()
            image = report["prepare"]["uuid"]
            print(f"Prepared image {image} in {report['prepare']['seconds']} s. Put it in .env as SANDBOX_IMAGE_UUID.")

        sizes = {}
        for mb in [int(x) for x in args.upload_mb.split(",") if x]:
            t0 = time.perf_counter()
            await sbx.upload(os.urandom(mb * 1024 * 1024))
            sizes[f"{mb}MB"] = round(time.perf_counter() - t0, 2)
        report["upload_seconds"] = sizes

        data_id = await sbx.upload(tiny_batch())
        script_id = await sbx.upload(PROBE_SCRIPT.encode())
        res = await sbx.run(image, "python /in/probe.py", files={"/in/data.parquet": data_id, "/in/probe.py": script_id},
                            networking=False, disposable=False, timeout_s=120)
        report["offline_run"] = {"ok": res.ok, "status": res.status, "exit_code": res.exit_code,
                                 "duration_s": res.duration_s, "wall_s": round(res.wall_s, 2),
                                 "stderr_tail": res.stderr[-800:], "operation_id": res.operation_id}
        if res.ok and res.result_image_uuid:
            report["offline_run"]["result"] = json.loads(await sbx.download(res.result_image_uuid, "/out/result.json"))
        print("offline run:", json.dumps(report["offline_run"], indent=1))

        conc = {}
        for n in (1, 4, 8):
            t0 = time.perf_counter()
            runs = await asyncio.gather(*(sbx.run(image, "sleep 5 && echo done", networking=False, timeout_s=60)
                                          for _ in range(n)), return_exceptions=True)
            conc[n] = {"wall_s": round(time.perf_counter() - t0, 1),
                       "ok": sum(1 for x in runs if not isinstance(x, Exception) and x.ok),
                       "errors": [str(x)[:200] for x in runs if isinstance(x, Exception)]}
            print(f"concurrency {n}: {conc[n]}")
        report["concurrency"] = conc

    (OUT / "sandbox_probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Wrote docs/phase0/sandbox_probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
