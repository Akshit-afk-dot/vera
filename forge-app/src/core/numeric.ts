// NumPy-compatible numeric helpers. The TypeScript engine must reproduce the Python engine (analysis/) closely enough
// that both produce the same flags and grades; test/parity.test.ts enforces it.

export const isFiniteNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** numpy.arange: n = ceil((stop - start) / step); values = start + i * ((start + step) - start). */
export function arange(start: number, stop: number, step: number): number[] {
  const n = Math.max(0, Math.ceil((stop - start) / step));
  const delta = start + step - start;
  return Array.from({ length: n }, (_, i) => start + i * delta);
}

export function median(values: number[]): number {
  const a = values.filter(Number.isFinite).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

/** numpy.percentile with the default linear method. */
export function percentile(values: number[], q: number): number {
  const a = values.filter(Number.isFinite).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const pos = ((a.length - 1) * q) / 100;
  const lo = Math.floor(pos), hi = Math.min(lo + 1, a.length - 1);
  return a[lo] + (a[hi] - a[lo]) * (pos - lo);
}

export function mean(a: number[]): number {
  return a.reduce((s, x) => s + x, 0) / a.length;
}

/** numpy.std (population, ddof = 0). */
export function std(a: number[]): number {
  const m = mean(a);
  return Math.sqrt(mean(a.map((x) => (x - m) ** 2)));
}

/** numpy.interp: clamps outside the range, linear inside; xp must be non-decreasing. */
export function interp(x: number, xp: number[], fp: number[]): number {
  const n = xp.length;
  if (x <= xp[0]) return x < xp[0] ? fp[0] : fp[0];
  if (x >= xp[n - 1]) return fp[n - 1];
  let lo = 0, hi = n; // upper_bound: first index with xp[idx] > x
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xp[mid] <= x) lo = mid + 1; else hi = mid;
  }
  const j = lo - 1;
  if (x === xp[j]) return fp[j];
  return fp[j] + ((fp[j + 1] - fp[j]) * (x - xp[j])) / (xp[j + 1] - xp[j]);
}

/** numpy.gradient on a uniform grid, edge_order = 1. */
export function gradient(f: number[], x: number[]): number[] {
  const n = f.length, out = new Array<number>(n);
  out[0] = (f[1] - f[0]) / (x[1] - x[0]);
  out[n - 1] = (f[n - 1] - f[n - 2]) / (x[n - 1] - x[n - 2]);
  for (let i = 1; i < n - 1; i++) {
    const hl = x[i] - x[i - 1], hr = x[i + 1] - x[i];
    out[i] = (hl * hl * f[i + 1] - hr * hr * f[i - 1] + (hr * hr - hl * hl) * f[i]) / (hl * hr * (hl + hr));
  }
  return out;
}

/** Gaussian smoothing equal to numpy.convolve(y, w / w.sum(), mode="same") with w = exp(-k^2 / (2 sigma^2)). */
export function smooth(y: number[], sigmaPts: number): number[] {
  const r = Math.floor(4 * sigmaPts);
  const w: number[] = [];
  for (let k = -r; k <= r; k++) w.push(Math.exp(-0.5 * (k / sigmaPts) ** 2));
  const s = w.reduce((a, b) => a + b, 0);
  const wn = w.map((x) => x / s);
  return y.map((_, i) => {
    let acc = 0;
    for (let k = -r; k <= r; k++) {
      const j = i - k; // convolution: y[j] * w[k]
      if (j >= 0 && j < y.length) acc += y[j] * wn[k + r];
    }
    return acc;
  });
}

/** Python round() to n decimals (ties to even at the binary value, close enough for reporting). */
export function round(x: number, n: number): number {
  const f = 10 ** n;
  return Math.round(x * f) / f;
}

export function argsort(a: number[]): number[] {
  return a.map((v, i) => [v, i] as [number, number]).sort((p, q) => p[0] - q[0] || p[1] - q[1]).map((p) => p[1]);
}
