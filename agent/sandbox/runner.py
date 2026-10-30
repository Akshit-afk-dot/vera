"""Where model-written code runs.

local   dev only: subprocess in a temp dir with a stripped environment (no API keys) and a timeout.
        Refuses to start when PUBLIC_DEPLOYMENT=1.
contree Nebius Token Factory Sandboxes over REST with networking disabled (agent/sandbox/contree_rest.py).
Both run the same trusted wrapper (job_files/run_job.py) around the model's normalizer.py.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

JOB_FILES = Path(__file__).resolve().parent / "job_files"


@dataclass
class JobResult:
    ok: bool
    exit_code: int | None
    duration_s: float
    stdout: str
    stderr: str
    output: Path | None
    operation_id: str | None = None
    runner: str = "local"
    extra: dict = field(default_factory=dict)


class LocalRunner:
    name = "local"

    def __init__(self, timeout_s: int = 900):
        if os.environ.get("PUBLIC_DEPLOYMENT") == "1":
            raise RuntimeError("the local runner is for development only and is disabled on public deployments")
        self.timeout_s = timeout_s

    def run_normalizer(self, code: str, input_path: Path, workdir: Path) -> JobResult:
        job = Path(tempfile.mkdtemp(prefix="vera-job-"))
        try:
            for f in JOB_FILES.iterdir():
                if f.suffix == ".py":
                    shutil.copy(f, job / f.name)
            (job / "normalizer.py").write_text(code, encoding="utf-8")
            out = job / "out" / "canonical.parquet"
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE") if k in os.environ}
            t0 = time.perf_counter()
            try:
                p = subprocess.run([sys.executable, "-I", str(job / "run_job.py"), str(input_path.resolve()), str(out)],
                                   cwd=job, env=env, capture_output=True, text=True, timeout=self.timeout_s)
                code_, so, se = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired as e:
                code_, so, se = None, e.stdout or "", f"timed out after {self.timeout_s} s"
            dur = time.perf_counter() - t0
            result_path = None
            if code_ == 0 and out.exists():
                workdir.mkdir(parents=True, exist_ok=True)
                result_path = workdir / "canonical.parquet"
                shutil.copy(out, result_path)
            return JobResult(code_ == 0 and result_path is not None, code_, dur, so[-4000:], se[-6000:], result_path)
        finally:
            shutil.rmtree(job, ignore_errors=True)


class ContreeRunner:
    """Token Factory Sandboxes. Needs SANDBOX_IMAGE_UUID: an image with pandas, pyarrow, scipy, openpyxl, h5py."""

    name = "contree"

    def __init__(self, timeout_s: int = 900):
        self.image = os.environ.get("SANDBOX_IMAGE_UUID")
        if not self.image:
            raise RuntimeError("Set SANDBOX_IMAGE_UUID (prepare it with scripts/phase0_sandbox.py)")
        self.timeout_s = timeout_s

    def run_normalizer(self, code: str, input_path: Path, workdir: Path) -> JobResult:
        return asyncio.run(self._run(code, input_path, workdir))

    async def _run(self, code: str, input_path: Path, workdir: Path) -> JobResult:
        from agent.sandbox.contree_rest import ContreeRest

        async with ContreeRest() as sbx:
            files = {f"/job/{f.name}": await sbx.upload(f.read_bytes()) for f in JOB_FILES.glob("*.py")}
            files["/job/normalizer.py"] = await sbx.upload(code.encode())
            files[f"/in/{input_path.name}"] = await sbx.upload(input_path.read_bytes())
            res = await sbx.run(self.image, f"python /job/run_job.py '/in/{input_path.name}' /out/canonical.parquet",
                                files=files, networking=False, disposable=False, timeout_s=self.timeout_s)
            out = None
            if res.ok and res.result_image_uuid:
                workdir.mkdir(parents=True, exist_ok=True)
                out = workdir / "canonical.parquet"
                out.write_bytes(await sbx.download(res.result_image_uuid, "/out/canonical.parquet"))
            return JobResult(res.ok and out is not None, res.exit_code, res.duration_s or res.wall_s,
                             res.stdout[-4000:], res.stderr[-6000:], out, res.operation_id, "contree",
                             {"result_image_uuid": res.result_image_uuid})


def make_runner(kind: str | None = None):
    kind = kind or os.environ.get("SANDBOX_RUNNER", "local")
    return {"local": LocalRunner, "contree": ContreeRunner}[kind]()
