// Deterministic regrading in the browser. Mirrors analysis/grading.py exactly (tests/test_grading_parity.py
// runs both on the same data). No model call is involved in a threshold change.
export const ORDER = ["A", "B", "C", "REJECT"];

export function referenceCapacity(channels, th) {
  if (th.basis === "nominal") {
    if (!th.nominal_capacity_ah) throw new Error("basis 'nominal' needs nominal_capacity_ah");
    return Number(th.nominal_capacity_ah);
  }
  const v = channels.map((c) => c.capacity_ah).filter((x) => x != null && Number.isFinite(x) && x > 0).sort((a, b) => a - b);
  if (!v.length) throw new Error("no valid capacities");
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

export function gradeChannel(ch, th, ref, medIr) {
  const types = new Set(ch.flags.map((f) => f.type));
  if (th.reject_on_flags.some((t) => types.has(t))) return "REJECT";
  if (ch.capacity_ah == null || !Number.isFinite(ch.capacity_ah)) return "REJECT";
  const capPct = (100 * ch.capacity_ah) / ref;
  const irPct = ch.ir_mohm != null && medIr ? (100 * ch.ir_mohm) / medIr : null;
  let g = ["A", "B", "C"].find((x) => capPct >= th.capacity_min_pct[x] && (irPct == null || irPct <= th.ir_max_pct[x])) || "REJECT";
  for (const f of ch.flags) {
    const cap = th.max_grade_by_severity[f.severity];
    if (cap && ORDER.indexOf(cap) > ORDER.indexOf(g)) g = cap;
  }
  return g;
}

export function regrade(results, th) {
  const ref = referenceCapacity(results.channels, th);
  const medIr = results.summary.median_ir_mohm;
  return results.channels.map((c) => gradeChannel(c, th, ref, medIr));
}
