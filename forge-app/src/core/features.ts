// Port of analysis/features.py. Canonical rows in, per-channel features out. Positive current = charge.
import { arange, argsort, gradient, interp, isFiniteNum, mean, median, round, smooth } from "./numeric.ts";

export interface CanonicalRow {
  channel_id: string; cycle: number; step: number; time_s: number; voltage_v: number; current_a: number;
}
export interface CycleRow {
  cycle: number; discharge_capacity_ah: number; charge_capacity_ah: number; ce: number | null;
  ir_mohm: number | null; mid_voltage_v: number | null;
}
export interface ChannelFeatures {
  channel_id: string; capacity_ah: number; ir_mohm: number | null; first_cycle_ce: number | null;
  capacity_slope_pct_per_cycle: number | null; dqdv_peak_v: number | null; noise_mv: number | null;
  mid_voltage_v: number | null; n_cycles: number; curve_dist_pct: number | null;
}
export interface Curve { q_ah: number[]; v: number[] }

export const VGRID = arange(3.45, 4.05, 0.002);
const OFFSETS_V = arange(-0.06, 0.0605, 0.001);
const CURVE_POINTS = 60;

function modes(i: number[]): number[] {
  const thr = Math.max(0.002, 0.01 * Math.max(...i.map(Math.abs)));
  return i.map((x) => (x > thr ? 1 : x < -thr ? -1 : 0));
}

function increments(t: number[], i: number[], mode: number[]): number[] {
  return t.map((tk, k) => {
    const dt = k === 0 ? 0 : tk - t[k - 1];
    const same = k > 0 && mode[k] === mode[k - 1];
    const iPrev = k === 0 ? i[0] : i[k - 1];
    return ((same ? 0.5 * (i[k] + iPrev) : i[k]) * dt) / 3600;
  });
}

function noiseMv(v: number[], mode: number[], t: number[]): number | null {
  const segId: number[] = [];
  let s = 0;
  mode.forEach((m, k) => { if (k === 0 || m !== mode[k - 1]) s++; segId.push(s); });
  const segStart = new Map<number, number>();
  segId.forEach((id, k) => { if (!segStart.has(id) || t[k] < segStart.get(id)!) segStart.set(id, t[k]); });
  const bySeg = new Map<number, number[]>();
  segId.forEach((id, k) => {
    if (mode[k] === 0 && t[k] - segStart.get(id)! >= 180) {
      if (!bySeg.has(id)) bySeg.set(id, []);
      bySeg.get(id)!.push(v[k]);
    }
  });
  const d2: number[] = [];
  for (const id of [...bySeg.keys()].sort((a, b) => a - b)) {
    const x = bySeg.get(id)!;
    for (let k = 0; k + 2 < x.length; k++) d2.push(x[k + 2] - 2 * x[k + 1] + x[k]);
  }
  if (!d2.length) return null;
  return (1.4826 * median(d2.map(Math.abs))) / Math.sqrt(6) * 1000;
}

function cycleFeatures(t: number[], v: number[], i: number[], mode: number[], dq: number[], cyc: number[]) {
  const rows: CycleRow[] = [];
  const curves: Record<number, Curve> = {};
  const cycles = [...new Set(cyc)].sort((a, b) => a - b);
  for (const c of cycles) {
    let dis = 0, chg = 0;
    const idx: number[] = [];
    cyc.forEach((x, k) => { if (x === c) { idx.push(k); if (dq[k] < 0) dis -= dq[k]; else if (dq[k] > 0) chg += dq[k]; } });
    let ir: number | null = null;
    const start = idx.find((k) => mode[k] === -1 && (k === 0 ? 0 : mode[k - 1]) !== -1);
    if (start !== undefined && start > 0) {
      const j = start, di = Math.abs(i[j]) - Math.abs(i[j - 1]);
      if (mode[j - 1] === 0 && t[j] - t[j - 1] <= 10 && di > 0) ir = ((v[j - 1] - v[j]) / di) * 1000;
    }
    const dIdx = idx.filter((k) => mode[k] === -1);
    const mid = dIdx.length ? median(dIdx.map((k) => v[k])) : null;
    rows.push({ cycle: c, discharge_capacity_ah: round(dis, 5), charge_capacity_ah: round(chg, 5),
      ce: chg > 0 ? round(dis / chg, 5) : null, ir_mohm: ir === null ? null : round(ir, 3),
      mid_voltage_v: mid === null ? null : round(mid, 4) });
    if (dIdx.length >= 5) {
      let acc = 0;
      const q = dIdx.map((k) => (acc -= dq[k]));
      const n = Math.min(CURVE_POINTS, q.length);
      const pick = Array.from({ length: n }, (_, p) => Math.trunc((p * (q.length - 1)) / Math.max(n - 1, 1)));
      curves[c] = { q_ah: pick.map((p) => round(q[p], 4)), v: pick.map((p) => round(v[dIdx[p]], 4)) };
    }
  }
  return { rows, curves };
}

type Shape = { vx: number[]; qy: number[] } | null;

function qvShape(v: number[], q: number[], currentA: number, irOhm: number | null): { shape: Shape; peak: number | null } {
  if (v.length < 10 || q[q.length - 1] <= 0) return { shape: null, peak: null };
  const vOcv = v.map((x) => x + Math.abs(currentA) * (irOhm ?? 0));
  const order = argsort(vOcv);
  const vx = order.map((k) => vOcv[k]), qy = order.map((k) => q[k] / q[q.length - 1]);
  const qn = VGRID.map((g) => interp(g, vx, qy));
  const dqdv = smooth(gradient(qn, VGRID).map((x) => -x), 5);
  let best = -Infinity, peak: number | null = null;
  VGRID.forEach((g, k) => { if (g > 3.5 && g < 4.0 && dqdv[k] > best) { best = dqdv[k]; peak = g; } });
  return { shape: { vx, qy }, peak };
}

export function curveDistance(shapes: Map<string, Shape>, ids: string[]): (number | null)[] {
  const valid = ids.filter((k) => shapes.get(k));
  if (valid.length < 5) return ids.map(() => null);
  const grids = valid.map((k) => VGRID.map((g) => interp(g, shapes.get(k)!.vx, shapes.get(k)!.qy)));
  const med = VGRID.map((_, j) => median(grids.map((gr) => gr[j])));
  return ids.map((k) => {
    const s = shapes.get(k);
    if (!s) return null;
    let best = Infinity;
    for (const off of OFFSETS_V) {
      let sq = 0;
      VGRID.forEach((g, j) => { sq += (interp(g + off, s.vx, s.qy) - med[j]) ** 2; });
      best = Math.min(best, Math.sqrt(sq / VGRID.length));
    }
    return round(best * 100, 4);
  });
}

export function channelFeatures(rows: CanonicalRow[]) {
  const byCh = new Map<string, CanonicalRow[]>();
  for (const r of rows) {
    if (!byCh.has(r.channel_id)) byCh.set(r.channel_id, []);
    byCh.get(r.channel_id)!.push(r);
  }
  const ids = [...byCh.keys()].sort();
  const features: ChannelFeatures[] = [];
  const cycles: Record<string, CycleRow[]> = {};
  const curves: Record<string, Record<number, Curve>> = {};
  const shapes = new Map<string, Shape>();
  for (const id of ids) {
    const g = byCh.get(id)!.map((r, k) => [r, k] as const).sort((a, b) => a[0].time_s - b[0].time_s || a[1] - b[1]).map((p) => p[0]);
    const t = g.map((r) => r.time_s), v = g.map((r) => r.voltage_v), i = g.map((r) => r.current_a), cyc = g.map((r) => r.cycle);
    const mode = modes(i), dq = increments(t, i, mode);
    const cf = cycleFeatures(t, v, i, mode, dq, cyc);
    cycles[id] = cf.rows;
    curves[id] = cf.curves;
    const last = cf.rows[cf.rows.length - 1], first = cf.rows[0];
    const caps = cf.rows.map((r) => r.discharge_capacity_ah);
    let slope: number | null = null;
    if (caps.length >= 3 && caps[caps.length - 1] > 0) {
      const x = caps.map((_, k) => k), mx = mean(x), my = mean(caps);
      const b = x.reduce((s, xk, k) => s + (xk - mx) * (caps[k] - my), 0) / x.reduce((s, xk) => s + (xk - mx) ** 2, 0);
      slope = round((b / caps[caps.length - 1]) * 100, 4);
    }
    const lastIdx = cyc.map((c, k) => (c === last.cycle && mode[k] === -1 ? k : -1)).filter((k) => k >= 0);
    let acc = 0;
    const q = lastIdx.map((k) => (acc -= dq[k]));
    const cur = lastIdx.length ? median(lastIdx.map((k) => i[k])) : 0;
    const { shape, peak } = qvShape(lastIdx.map((k) => v[k]), q, cur, last.ir_mohm ? last.ir_mohm / 1000 : null);
    shapes.set(id, shape);
    const noise = noiseMv(v, mode, t);
    features.push({ channel_id: id, capacity_ah: last.discharge_capacity_ah, ir_mohm: last.ir_mohm, first_cycle_ce: first.ce,
      capacity_slope_pct_per_cycle: slope, dqdv_peak_v: peak === null ? null : round(peak, 4),
      noise_mv: noise === null ? null : round(noise, 4), mid_voltage_v: last.mid_voltage_v, n_cycles: cf.rows.length,
      curve_dist_pct: null });
  }
  const dist = curveDistance(shapes, ids);
  features.forEach((f, k) => { f.curve_dist_pct = isFiniteNum(dist[k]) ? dist[k] : null; });
  return { features, cycles, curves };
}
