"""Deterministic grading. Regrading after a threshold edit calls only this module (no LLM)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np

ORDER = ("A", "B", "C", "REJECT")


def reference_capacity(capacities: Iterable[float | None], basis: str, nominal_capacity_ah: float | None) -> float:
    if basis == "nominal":
        if not nominal_capacity_ah:
            raise ValueError("basis='nominal' needs nominal_capacity_ah")
        return float(nominal_capacity_ah)
    vals = np.array([c for c in capacities if c is not None and np.isfinite(c) and c > 0], dtype=float)
    if vals.size == 0:
        raise ValueError("no valid capacities to compute a batch median")
    return float(np.median(vals))


def grade_channel(
    capacity_ah: float | None,
    ir_mohm: float | None,
    flags: Iterable[Mapping],
    *,
    reference_capacity_ah: float,
    median_ir_mohm: float | None,
    capacity_min_pct: Mapping[str, float],
    ir_max_pct: Mapping[str, float],
    reject_on_flags: Iterable[str],
    max_grade_by_severity: Mapping[str, str],
) -> str:
    """flags: dicts with at least 'type' and 'severity' (contracts.models.Flag shape)."""
    flags = list(flags)
    if {f["type"] for f in flags} & set(reject_on_flags):
        return "REJECT"
    if capacity_ah is None or not np.isfinite(capacity_ah):
        return "REJECT"
    cap_pct = 100.0 * capacity_ah / reference_capacity_ah
    ir_pct = 100.0 * ir_mohm / median_ir_mohm if ir_mohm is not None and median_ir_mohm else None
    grade = next((g for g in ORDER[:3] if cap_pct >= capacity_min_pct[g]
                  and (ir_pct is None or ir_pct <= ir_max_pct[g])), "REJECT")
    caps = [max_grade_by_severity[f["severity"]] for f in flags if f["severity"] in max_grade_by_severity]
    return max([grade, *caps], key=ORDER.index)
