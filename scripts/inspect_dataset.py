"""Resolve a downloaded dataset's real format: safely extract zips (nested too), peek every data file with the
same generic S1 code the agent uses, and write data/cache/peeks/<dataset>.json (gitignored).

Run: uv run python -I scripts/inspect_dataset.py <dataset-dir-name> [--show N]
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.ingest.peek import peek, safe_extract, to_text  # noqa: E402

DATA_EXT = {".mat", ".csv", ".txt", ".xlsx", ".xls", ".tsv", ".h5", ".json"}


def extract_all(root: Path) -> None:
    """Extract every zip under root into <zip-stem>/ next to it, repeating for nested zips."""
    seen: set[Path] = set()
    while True:
        zips = [z for z in root.rglob("*.zip") if z not in seen and zipfile.is_zipfile(z)]
        if not zips:
            return
        for z in zips:
            seen.add(z)
            dest = z.with_suffix("")
            if not dest.exists():
                files = safe_extract(z, dest)
                print(f"extracted {z.relative_to(root)} -> {len(files)} files")


def main() -> int:
    name = sys.argv[1]
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 2
    data_dir = Path(os.environ.get("DATA_DIR", ROOT / "data" / "raw"))
    root = (data_dir if data_dir.is_absolute() else ROOT / data_dir) / name
    extract_all(root)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in DATA_EXT)
    print(f"{len(files)} data files under {root}")
    peeks = {}
    for p in files:
        rel = str(p.relative_to(root))
        try:
            peeks[rel] = peek(p)
        except Exception as e:  # noqa: BLE001 - record and continue; the point is to see what breaks
            peeks[rel] = {"error": f"{type(e).__name__}: {e}"}
    out = ROOT / "data" / "cache" / "peeks" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(peeks, default=str, indent=1), encoding="utf-8", newline="\n")
    for rel, s in peeks.items():
        print(f"- {rel}: {s.get('kind', 'error')} {s.get('bytes', '')} {s.get('error', '')}")
    for rel in [r for r in peeks if r.endswith(".mat")][:show] + [r for r in peeks if not r.endswith(".mat")][:show]:
        print(f"\n===== {rel}\n{to_text(peeks[rel], 6000)}")
    print(f"\nWrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
