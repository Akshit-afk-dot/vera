"""Thin async client for the Token Factory Sandboxes REST API.

Why REST and not contree-sdk: SDK 0.3.6 exposes no networking switch, and every analysis run must
start with `networking.enabled=false` (docs: /sandboxes/guides/configure-networking-and-secrets).
The SDK is still used for one-off image preparation (scripts/phase0_sandbox.py).
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"
PENDING_STATES = {"PENDING", "ASSIGNED", "EXECUTING"}


class SandboxError(RuntimeError):
    pass


@dataclass
class RunResult:
    operation_id: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    signal: int | None
    truncated: bool
    result_image_uuid: str | None
    duration_s: float | None
    wall_s: float
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "SUCCESS" and self.exit_code == 0 and not self.timed_out and self.signal in (None, -1)


def _decode(stream: dict[str, Any] | None) -> tuple[str, bool]:
    if not stream:
        return "", False
    value, enc = stream.get("value", ""), stream.get("encoding", "utf-8")
    text = base64.b64decode(value).decode("utf-8", "replace") if enc == "base64" else value
    return text, bool(stream.get("truncated"))


class ContreeRest:
    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        project_id = project_id or os.environ.get("NEBIUS_PROJECT_ID")
        if not api_key or not project_id:
            raise SandboxError("Set NEBIUS_API_KEY and NEBIUS_PROJECT_ID in .env")
        base = (base_url or os.environ.get("CONTREE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=f"{base}/v1/",
            headers={"Authorization": f"Bearer {api_key}", "Project": project_id},
            timeout=httpx.Timeout(30, read=120),
            transport=transport,
        )

    async def __aenter__(self) -> ContreeRest:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def whoami(self) -> httpx.Response:
        return await self._http.get("whoami")

    async def list_images(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._http.get("images", params=params)
        r.raise_for_status()
        body = r.json()
        return body.get("images", body) if isinstance(body, dict) else body

    async def upload(self, data: bytes) -> str:
        r = await self._http.post("files", content=data, headers={"Content-Type": "application/octet-stream"})
        r.raise_for_status()
        return r.json()["uuid"]

    async def spawn(
        self,
        image: str,
        command: str,
        *,
        files: dict[str, str] | None = None,
        networking: bool = False,
        disposable: bool = True,
        timeout_s: int = 300,
        truncate_output_at: int = 1_048_576,
        env: dict[str, str] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "image": image,
            "command": command,
            "shell": True,
            "networking": {"enabled": networking},
            "disposable": disposable,
            "timeout": timeout_s,
            "truncate_output_at": truncate_output_at,
            "preserve_env": False,
        }
        if files:
            body["files"] = {path: {"uuid": uuid, "mode": "0644"} for path, uuid in files.items()}
        if env:
            body["env"] = env
        r = await self._http.post("instances", json=body)
        if r.status_code != 201:
            raise SandboxError(f"spawn rejected: HTTP {r.status_code} {r.text[:500]}")
        return r.json()["uuid"]

    async def wait(self, operation_id: str, deadline_s: float) -> dict[str, Any]:
        end = time.monotonic() + deadline_s
        while True:
            r = await self._http.get(f"operations/{operation_id}")
            r.raise_for_status()
            op = r.json()
            if op.get("status") not in PENDING_STATES:
                return op
            if time.monotonic() > end:
                raise TimeoutError(f"operation {operation_id} still {op.get('status')}; inspect before resubmitting")
            ra = r.headers.get("Retry-After", "1")
            await asyncio.sleep(max(0.5, min(int(ra) if ra.isdecimal() else 1, 5)))

    async def run(self, image: str, command: str, **kw: Any) -> RunResult:
        t0 = time.monotonic()
        op_id = await self.spawn(image, command, **kw)
        op = await self.wait(op_id, deadline_s=kw.get("timeout_s", 300) + 120)
        result = (op.get("metadata") or {}).get("result") or {}
        state = result.get("state") or {}
        out, t1 = _decode(result.get("stdout"))
        err, t2 = _decode(result.get("stderr"))
        return RunResult(
            operation_id=op_id,
            status=op.get("status", "UNKNOWN"),
            exit_code=state.get("exit_code"),
            stdout=out,
            stderr=err,
            timed_out=bool(state.get("timed_out")),
            signal=state.get("signal"),
            truncated=t1 or t2,
            result_image_uuid=op.get("result_image_uuid"),
            duration_s=op.get("duration"),
            wall_s=time.monotonic() - t0,
            raw=op,
        )

    async def download(self, image_uuid: str, path: str) -> bytes:
        r = await self._http.get(f"inspect/{image_uuid}/download", params={"path": path})
        r.raise_for_status()
        return r.content

    async def cancel(self, operation_id: str) -> None:
        await self._http.delete(f"operations/{operation_id}")
