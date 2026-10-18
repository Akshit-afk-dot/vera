"""Cross-platform task runner. `make <target>` calls this; on Windows without make run
`uv run python scripts/tasks.py <target>`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(*cmd: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    code = subprocess.call(list(cmd), cwd=cwd, shell=sys.platform == "win32" and cmd[0] in {"npm", "npx"})
    if code:
        sys.exit(code)


def setup() -> None:
    sh("uv", "sync")
    sh("git", "config", "core.hooksPath", ".githooks")
    if (ROOT / "web" / "package.json").exists():
        sh("npm", "install", cwd=ROOT / "web")


def test() -> None:
    sh("uv", "run", "pytest", "-q")


def lint() -> None:
    sh("uv", "run", "ruff", "check", ".")


def contracts() -> None:
    sh("uv", "run", "python", "scripts/export_contracts.py")


def phase0() -> None:
    sh("uv", "run", "python", "scripts/phase0_models.py")
    sh("uv", "run", "python", "scripts/phase0_sandbox.py")


def secrets() -> None:
    sh("uv", "run", "python", "scripts/secret_scan.py", "--all")


def not_yet(name: str, phase: str):
    def run() -> None:
        sys.exit(f"`{name}` lands in {phase}; see CLAUDE.md §11.")

    return run


TASKS = {
    "setup": setup,
    "test": test,
    "lint": lint,
    "contracts": contracts,
    "phase0": phase0,
    "secrets": secrets,
    "dev": not_yet("dev", "Phase 1 (server skeleton)"),
    "synth": not_yet("synth", "Phase 2 (synthetic generator)"),
    "eval": not_yet("eval", "Phase 3 (eval harness)"),
    "demo": not_yet("demo", "Phase 3 (replay mode)"),
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        sys.exit(f"usage: tasks.py {{{','.join(TASKS)}}}")
    TASKS[sys.argv[1]]()
