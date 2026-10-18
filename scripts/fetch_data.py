"""Download the public datasets a script can reach into $DATA_DIR/<name>/ and record sizes and SHA-256 in
data/manifest.json (committed; the data itself never is). Manual-only datasets print instructions.

Run: uv run python scripts/fetch_data.py [nasa oxford ...] | --list
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
ORA = "https://ora.ox.ac.uk/objects/uuid:03ba4b01-cfed-46d3-9b1a-7d4a7bdf6fac/files"

DATASETS: dict[str, dict] = {
    "nasa": {
        "title": "NASA PCoE Li-ion battery aging (18650 cells)",
        "terms": "Use at own risk; acknowledge the NASA Prognostics Center of Excellence data repository and donors",
        "files": {"battery_data_set.zip": "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"},
    },
    "oxford": {
        "title": "Oxford Battery Degradation Dataset 1 (8 Kokam 740 mAh pouch cells)",
        "terms": "ODbL 1.0: credit the source, do not re-host",
        "files": {
            "Oxford_Battery_Degradation_Dataset_1.mat": f"{ORA}/m5ac36a1e2073852e4f1f7dee647909a7",
            "Readme.txt": f"{ORA}/m43cc05e7c5f1245f4895d9dbd495e52f",
        },
    },
}
MANUAL = {
    "michigan": "Browser or Globus from https://doi.org/10.7302/pa3f-4w30 (2.37 GB; scripted download returns 403)",
    "mit": "Browser from https://data.matr.io/1/ (site needs JavaScript; file format not yet verified)",
}


def data_dir() -> Path:
    load_dotenv(ROOT / ".env")
    d = Path(os.environ.get("DATA_DIR", "data/raw"))
    return d if d.is_absolute() else ROOT / d


def download(url: str, dest: Path) -> dict:
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=300),
                      headers={"User-Agent": "vera-fetch/0.1"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done, t0, last = 0, time.monotonic(), 0.0
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if time.monotonic() - last > 5:
                    last = time.monotonic()
                    pct = f"{100 * done / total:.0f}%" if total else "?"
                    print(f"  {dest.name}: {done / 1e6:.0f} MB ({pct}, {done / 1e6 / (last - t0 + 1e-9):.1f} MB/s)", flush=True)
    if total and done != total:
        raise OSError(f"{dest.name}: got {done} bytes, expected {total}")
    part.replace(dest)
    return {"url": url, "bytes": done}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if "--list" in sys.argv or len(sys.argv) == 1:
        for k, v in DATASETS.items():
            print(f"{k:10s} {v['title']}  [{v['terms']}]")
        for k, v in MANUAL.items():
            print(f"{k:10s} MANUAL: {v}")
        return 0
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    for name in sys.argv[1:]:
        if name in MANUAL:
            print(f"{name}: manual download. {MANUAL[name]}")
            continue
        spec = DATASETS[name]
        out = data_dir() / name
        out.mkdir(parents=True, exist_ok=True)
        entry = manifest.setdefault(name, {"title": spec["title"], "terms": spec["terms"], "files": {}})
        for fname, url in spec["files"].items():
            dest = out / fname
            known = entry["files"].get(fname, {})
            if dest.exists() and known.get("bytes") == dest.stat().st_size:
                print(f"{name}/{fname}: already present ({known['bytes'] / 1e6:.1f} MB)")
                continue
            print(f"{name}/{fname}: downloading {url}", flush=True)
            info = download(url, dest)
            info.update(sha256=sha256(dest), fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
            entry["files"][fname] = info
            print(f"{name}/{fname}: {info['bytes'] / 1e6:.1f} MB sha256 {info['sha256'][:16]}…")
            MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
