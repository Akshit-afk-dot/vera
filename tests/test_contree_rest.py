import base64
import json

import httpx

from agent.sandbox.contree_rest import ContreeRest


def make_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    polls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/v1/files"):
            return httpx.Response(201, json={"uuid": "file-1"})
        if path.endswith("/v1/instances"):
            return httpx.Response(201, json={"uuid": "op-1"})
        if path.endswith("/v1/operations/op-1"):
            polls["n"] += 1
            if polls["n"] == 1:
                return httpx.Response(200, json={"status": "EXECUTING"}, headers={"Retry-After": "0"})
            return httpx.Response(200, json={
                "status": "SUCCESS", "duration": 1.5, "result_image_uuid": "img-2",
                "metadata": {"result": {
                    "state": {"exit_code": 0, "timed_out": False, "signal": None},
                    "stdout": {"encoding": "base64", "value": base64.b64encode(b"probe-ok\n").decode()},
                    "stderr": {"encoding": "utf-8", "value": "", "truncated": False},
                }}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_run_spawns_offline_and_decodes_output():
    seen: list[httpx.Request] = []
    async with ContreeRest("k", "p", transport=make_transport(seen)) as sbx:
        fid = await sbx.upload(b"data")
        res = await sbx.run("img-1", "python /in/x.py", files={"/in/x.py": fid})

    assert res.ok and res.stdout == "probe-ok\n" and res.result_image_uuid == "img-2"
    spawn = next(r for r in seen if r.url.path.endswith("/v1/instances"))
    body = json.loads(spawn.content)
    assert body["networking"] == {"enabled": False}  # analysis runs are offline by default
    assert body["preserve_env"] is False
    assert body["files"] == {"/in/x.py": {"uuid": "file-1", "mode": "0644"}}
    assert spawn.headers["Project"] == "p" and spawn.headers["Authorization"] == "Bearer k"
