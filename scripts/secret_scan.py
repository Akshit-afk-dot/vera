"""Dependency-free secret scan for the pre-commit hook. CI additionally runs gitleaks on the full
history. Usage: secret_scan.py (staged files) | secret_scan.py --all (tracked files)."""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = [
    ("env assignment", re.compile(r"(?i)\b(NEBIUS_API_KEY|TAVILY_API_KEY|[A-Z_]*SECRET[A-Z_]*|[A-Z_]*TOKEN)\s*[=:]\s*['\"]?([A-Za-z0-9._\-]{16,})")),
    ("bearer token", re.compile(r"(?i)bearer\s+([A-Za-z0-9._\-]{24,})")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("tavily key", re.compile(r"\btvly-[A-Za-z0-9\-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]
# Values that are clearly placeholders, not secrets.
PLACEHOLDER = re.compile(r"(?i)(your|example|placeholder|redacted|xxxx|\$\{?[A-Z_]+\}?|os\.environ|getenv)")
FORBIDDEN_FILES = re.compile(r"(^|/)\.env($|\.(?!example$)[^/]+$)")


def files(all_tracked: bool) -> list[str]:
    cmd = ["git", "ls-files"] if all_tracked else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    return [f for f in subprocess.check_output(cmd, text=True).splitlines() if f]


def main() -> int:
    problems = []
    for path in files("--all" in sys.argv):
        if FORBIDDEN_FILES.search(path):
            problems.append(f"{path}: env file must never be committed")
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS:
                m = pattern.search(line)
                if m and not PLACEHOLDER.search(m.group(0)):
                    problems.append(f"{path}:{lineno}: possible {name}")
    if problems:
        print("Secret scan failed:\n  " + "\n  ".join(problems))
        print("If this is a false positive, adjust scripts/secret_scan.py rather than skipping the hook.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
