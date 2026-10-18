"""S1 'peek': a compact, format-generic structural summary of an unknown file for the planner.

No per-vendor logic: CSV/text -> first lines + sniffed delimiter; Excel -> sheets and first rows; MATLAB/HDF5 ->
tree of fields with shapes, dtypes, ranges and value counts of short strings; zip -> member list.
Parses untrusted bytes, so in production it runs inside the sandbox (plain numpy/scipy/h5py/openpyxl).
"""

from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

MAX_DEPTH = 7
MAX_FIELDS = 40


def peek(path: str | Path, n_lines: int = 40) -> dict[str, Any]:
    p = Path(path)
    ext = p.suffix.lower()
    head = p.open("rb").read(8)
    base = {"name": p.name, "bytes": p.stat().st_size}
    if head.startswith(b"PK\x03\x04") and ext not in {".xlsx", ".xlsm"}:
        return {**base, "kind": "zip", **peek_zip(p)}
    if ext in {".xlsx", ".xlsm"}:
        return {**base, "kind": "excel", **peek_excel(p)}
    if ext == ".mat" or head.startswith(b"\x89HDF"):
        return {**base, "kind": "mat", **peek_mat(p)}
    return {**base, "kind": "text", **peek_text(p, n_lines)}


def peek_text(p: Path, n_lines: int) -> dict[str, Any]:
    raw = p.open("rb").read(1 << 16)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()[:n_lines]
    with p.open("rb") as f:
        n_total = sum(1 for _ in f)
    return {"encoding": enc, "sniffed_delimiter": sniff_delimiter(lines), "total_lines": n_total, "first_lines": lines}


def sniff_delimiter(lines: list[str]) -> str | None:
    """Pick the delimiter whose per-line count is most consistent (then largest) over the last lines.
    csv.Sniffer gives up on preambles plus decimal commas, which tester exports often have."""
    body = [ln for ln in lines if ln.strip()][-20:]
    best: tuple[tuple[float, int], str] | None = None
    for d in ",;\t|":
        count, freq = Counter(ln.count(d) for ln in body).most_common(1)[0] if body else (0, 0)
        if count == 0:
            continue
        score = (freq / len(body), count)
        if best is None or score > best[0]:
            best = (score, d)
    return best[1] if best else None


def peek_excel(p: Path, n_rows: int = 8, max_sheets: int = 6) -> dict[str, Any]:
    from openpyxl import load_workbook

    wb = load_workbook(p, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets[:max_sheets]:
        rows = [[c for c in row] for row in ws.iter_rows(max_row=n_rows, values_only=True)]
        sheets.append({"name": ws.title, "dims": ws.calculate_dimension(), "first_rows": rows})
    return {"sheet_names": wb.sheetnames, "n_sheets": len(wb.sheetnames), "sheets": sheets}


def peek_zip(p: Path) -> dict[str, Any]:
    with zipfile.ZipFile(p) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        return {"n_members": len(infos),
                "members": [{"name": i.filename, "bytes": i.file_size} for i in infos[:200]]}


def peek_mat(p: Path) -> dict[str, Any]:
    from scipy.io import loadmat

    try:
        data = loadmat(p, simplify_cells=True)
        tree = {k: summarize(v) for k, v in data.items() if not k.startswith("__")}
        return {"mat_version": "v5", "tree": tree}
    except (NotImplementedError, ValueError):
        import h5py

        with h5py.File(p, "r") as f:
            return {"mat_version": "v7.3/hdf5", "tree": _h5_tree(f, 0)}


def summarize(v: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return "…"
    if isinstance(v, dict):
        keys = list(v)[:MAX_FIELDS]
        out = {k: summarize(v[k], depth + 1) for k in keys}
        if len(v) > MAX_FIELDS:
            out["…"] = f"{len(v) - MAX_FIELDS} more fields"
        return out
    if isinstance(v, (list, tuple)) or (isinstance(v, np.ndarray) and v.dtype == object):
        items = list(v)
        if items and all(isinstance(i, dict) for i in items):
            return _summarize_records(items, depth)
        return {"list_len": len(items), "first": summarize(items[0], depth + 1) if items else None}
    if isinstance(v, np.ndarray):
        return _summarize_array(v)
    if isinstance(v, str):
        return v[:60]
    if isinstance(v, (int, float, np.number, bool)):
        return v.item() if isinstance(v, np.generic) else v
    return type(v).__name__


def _summarize_array(a: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {"dtype": str(a.dtype), "shape": list(a.shape)}
    if a.size and np.issubdtype(a.dtype, np.complexfloating):
        out["note"] = "complex; min/max/head are magnitudes"
        a = np.abs(a)
    if a.size and np.issubdtype(a.dtype, np.number):
        f = a.astype(float).ravel()
        fin = f[np.isfinite(f)]
        if fin.size:
            out.update(min=float(fin.min()), max=float(fin.max()), head=[round(float(x), 6) for x in f[:5]])
    elif a.size and a.dtype.kind in "US":
        out["values"] = dict(Counter(map(str, a.ravel())).most_common(8))
    return out


def _signature(v: Any) -> Any:
    """Nested field structure of a record, ignoring values (so charge vs discharge records separate)."""
    if isinstance(v, dict):
        return tuple(sorted((k, _signature(x)) for k, x in v.items()))
    return "leaf"


def _summarize_records(items: list[dict], depth: int) -> dict[str, Any]:
    """A list of structs (e.g. one per cycle): group by nested field structure, count short-string values."""
    variants: dict[Any, list[dict]] = {}
    for it in items:
        variants.setdefault(_signature(it), []).append(it)
    out: dict[str, Any] = {"records": len(items), "variants": []}
    for group in variants.values():
        keys = list(group[0])
        strings = {k: dict(Counter(str(g[k]) for g in group).most_common(6))
                   for k in keys if all(isinstance(g[k], str) and len(g[k]) <= 30 for g in group)}
        out["variants"].append({"count": len(group), "fields": keys, "string_values": strings,
                                "example": summarize(group[0], depth + 1)})
    return out


def _h5_tree(node: Any, depth: int) -> Any:
    import h5py

    if depth > MAX_DEPTH:
        return "…"
    if isinstance(node, h5py.Dataset):
        return {"dtype": str(node.dtype), "shape": list(node.shape)}
    keys = list(node.keys())
    out = {k: _h5_tree(node[k], depth + 1) for k in keys[:MAX_FIELDS]}
    if len(keys) > MAX_FIELDS:
        out["…"] = f"{len(keys) - MAX_FIELDS} more"
    return out


def to_text(summary: dict[str, Any], limit: int = 12_000) -> str:
    """Compact JSON-ish rendering for prompts and logs."""
    import json

    s = json.dumps(summary, default=str, indent=1)
    return s if len(s) <= limit else s[:limit] + "\n… (truncated)"


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a zip, refusing absolute paths and '..' (zip-slip). Returns extracted file paths."""
    dest = dest.resolve()
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest):
                raise ValueError(f"unsafe path in zip: {info.filename}")
            if info.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            out.append(target)
    return out
