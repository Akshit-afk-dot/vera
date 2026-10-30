// Port of analysis/rules.py: batch-relative robust z-scores plus absolute sanity limits.
import { median } from "./numeric.ts";
import { robustZ } from "./stats.ts";

export const Z_FLAG = 3.5;
const DEAD_CAPACITY_FRACTION = 0.1;
const NOISE_SENSITIVE = new Set(["HIGH_IR", "CURVE_SHAPE"]);

export type FaultType = "LOW_CAPACITY" | "HIGH_IR" | "LOW_CE" | "CURVE_SHAPE" | "CAPACITY_CREEP_UP" | "NOISY_OR_DEAD_CHANNEL";
export interface Evidence { metric: string; value: number; unit: string; batch_median: number; robust_z: number | null; threshold: string }
export interface Flag { type: FaultType; severity: "low" | "medium" | "high"; evidence: Evidence[]; explanation?: string | null }

export const RULES: [string, FaultType, -1 | 1, string, "linear" | "log"][] = [
  ["capacity_ah", "LOW_CAPACITY", -1, "Ah", "linear"],
  ["ir_mohm", "HIGH_IR", 1, "mOhm", "linear"],
  ["first_cycle_ce", "LOW_CE", -1, "", "linear"],
  ["curve_dist_pct", "CURVE_SHAPE", 1, "%", "log"],
  ["capacity_slope_pct_per_cycle", "CAPACITY_CREEP_UP", 1, "%/cycle", "linear"],
  ["noise_mv", "NOISY_OR_DEAD_CHANNEL", 1, "mV", "log"],
];

const r = (x: number, n: number) => Math.round(x * 10 ** n) / 10 ** n;
export const severity = (z: number) => (Math.abs(z) < 5 ? "low" : Math.abs(z) < 8 ? "medium" : "high");

export function detect(ids: string[], features: Record<string, (number | null)[]>, zFlag = Z_FLAG): Record<string, Flag[]> {
  const flags: Record<string, Flag[]> = Object.fromEntries(ids.map((id) => [id, []]));
  const cap = (features.capacity_ah ?? []).map((x) => (x === null ? NaN : x));
  const dead = new Set<string>();
  if (cap.length) {
    const medCap = median(cap);
    ids.forEach((id, k) => {
      const c = cap[k];
      if (!Number.isFinite(c) || c < DEAD_CAPACITY_FRACTION * medCap) {
        dead.add(id);
        flags[id].push({ type: "NOISY_OR_DEAD_CHANNEL", severity: "high", evidence: [{ metric: "capacity_ah",
          value: Number.isFinite(c) ? r(c, 4) : 0, unit: "Ah", batch_median: r(medCap, 4), robust_z: null,
          threshold: `capacity < ${DEAD_CAPACITY_FRACTION * 100}% of batch median` }] });
      }
    });
  }
  const live = ids.map((id) => !dead.has(id));
  for (const [name, fault, direction, unit, scale] of RULES) {
    if (!(name in features)) continue;
    const vals = features[name].map((x) => (x === null ? NaN : x));
    const scored = scale === "log" ? vals.map((x) => (x > 0 ? Math.log(x) : NaN)) : vals;
    const liveScored = scored.filter((_, k) => live[k]);
    if (liveScored.filter(Number.isFinite).length < 5) continue;
    const zLive = robustZ(liveScored).z;
    const z: number[] = new Array(vals.length).fill(NaN);
    let p = 0;
    live.forEach((l, k) => { if (l) z[k] = zLive[p++]; });
    const med = median(vals.filter((_, k) => live[k]));
    const rule = `robust_z${scale === "log" ? " (log scale)" : ""} ${direction < 0 ? "<" : ">"} ${direction < 0 ? -zFlag : zFlag}`;
    ids.forEach((id, k) => {
      const zi = z[k];
      if (Number.isFinite(zi) && (direction < 0 ? zi < -zFlag : zi > zFlag)) {
        flags[id].push({ type: fault, severity: severity(zi), evidence: [{ metric: name, value: r(vals[k], 5), unit,
          batch_median: r(med, 5), robust_z: r(zi, 2), threshold: rule }] });
      }
    });
  }
  for (const id of ids) {
    if (flags[id].some((f) => f.type === "NOISY_OR_DEAD_CHANNEL")) flags[id] = flags[id].filter((f) => !NOISE_SENSITIVE.has(f.type));
  }
  return flags;
}
