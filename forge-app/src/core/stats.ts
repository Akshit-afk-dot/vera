import { median, percentile, std } from "./numeric.ts";

const MAD_TO_SIGMA = 1.4826;

/** Median and MAD-based sigma over finite values; falls back to IQR, then std, then 1e-12 (as analysis/stats.py). */
export function robustCenterScale(values: number[]): [number, number] {
  const v = values.filter(Number.isFinite);
  if (!v.length) return [NaN, NaN];
  const med = median(v);
  let scale = MAD_TO_SIGMA * median(v.map((x) => Math.abs(x - med)));
  if (scale <= 0) scale = (percentile(v, 75) - percentile(v, 25)) / 1.349;
  if (scale <= 0) scale = std(v);
  return [med, Math.max(scale, 1e-12)];
}

export function robustZ(values: number[]): { z: number[]; med: number; scale: number } {
  const [med, scale] = robustCenterScale(values);
  return { z: values.map((x) => (x - med) / scale), med, scale };
}
