// Port of analysis/grading.py (same logic as web/grading.js).
import { median } from "./numeric.ts";
import type { Flag } from "./rules.ts";

export type Grade = "A" | "B" | "C" | "REJECT";
export const ORDER: Grade[] = ["A", "B", "C", "REJECT"];
export interface Thresholds {
  basis: "batch_median" | "nominal"; nominal_capacity_ah: number | null;
  capacity_min_pct: Record<"A" | "B" | "C", number>; ir_max_pct: Record<"A" | "B" | "C", number>;
  reject_on_flags: string[]; max_grade_by_severity: Partial<Record<"low" | "medium" | "high", Grade>>;
}
export const DEFAULT_THRESHOLDS: Thresholds = {
  basis: "batch_median", nominal_capacity_ah: null, capacity_min_pct: { A: 98, B: 95, C: 90 },
  ir_max_pct: { A: 115, B: 130, C: 160 }, reject_on_flags: ["NOISY_OR_DEAD_CHANNEL"],
  max_grade_by_severity: { high: "C", medium: "B" },
};

export function referenceCapacity(capacities: (number | null)[], th: Thresholds): number {
  if (th.basis === "nominal") {
    if (!th.nominal_capacity_ah) throw new Error("basis 'nominal' needs nominal_capacity_ah");
    return th.nominal_capacity_ah;
  }
  const v = capacities.filter((c): c is number => c !== null && Number.isFinite(c) && c > 0);
  if (!v.length) throw new Error("no valid capacities to compute a batch median");
  return median(v);
}

export function gradeChannel(capacity: number | null, ir: number | null, flags: Flag[], ref: number, medIr: number | null, th: Thresholds): Grade {
  const types = new Set(flags.map((f) => f.type));
  if (th.reject_on_flags.some((t) => types.has(t as Flag["type"]))) return "REJECT";
  if (capacity === null || !Number.isFinite(capacity)) return "REJECT";
  const capPct = (100 * capacity) / ref;
  const irPct = ir !== null && medIr ? (100 * ir) / medIr : null;
  let g: Grade = (["A", "B", "C"] as const).find((x) => capPct >= th.capacity_min_pct[x] && (irPct === null || irPct <= th.ir_max_pct[x])) ?? "REJECT";
  for (const f of flags) {
    const cap = th.max_grade_by_severity[f.severity];
    if (cap && ORDER.indexOf(cap) > ORDER.indexOf(g)) g = cap;
  }
  return g;
}
