// Port of agent/ingest/checks.py validate(): the model never decides whether its own mapping is acceptable.
import type { CanonicalRow } from "./features.ts";
import { median } from "./numeric.ts";

export interface Check { name: string; ok: boolean; detail: string }

export function validate(rows: CanonicalRow[]): { checks: Check[]; ok: boolean; n_channels: number; n_cycles: number; n_rows: number } {
  const checks: Check[] = [];
  const add = (name: string, ok: boolean, detail: string) => checks.push({ name, ok, detail });
  const byCh = new Map<string, CanonicalRow[]>();
  for (const r of rows) { if (!byCh.has(r.channel_id)) byCh.set(r.channel_id, []); byCh.get(r.channel_id)!.push(r); }
  add("at least one channel", byCh.size >= 1, `${byCh.size} channels, ${rows.length} rows`);
  if (!byCh.size) return { checks, ok: false, n_channels: 0, n_cycles: 0, n_rows: 0 };

  let vmax = 0, imax = 0;
  for (const r of rows) { vmax = Math.max(vmax, Math.abs(r.voltage_v)); imax = Math.max(imax, Math.abs(r.current_a)); }
  const unitsOk = vmax < 6 && imax < 200;
  add("units converted (V, A)", unitsOk, `max |V| ${vmax.toPrecision(3)}, max |I| ${imax.toPrecision(3)}${unitsOk ? "" : " (looks like mV/mA left unconverted)"}`);

  const active = [...byCh.values()].filter((rs) => rs.some((r) => Math.abs(r.current_a) > 1e-3));
  const plausible = active.length ? active.filter((rs) => { const m = median(rs.map((r) => r.voltage_v)); return m > 1.5 && m < 4.8; }).length / active.length : 0;
  add("plausible cell voltage", plausible >= 0.9, `${Math.round(plausible * 100)}% of active channels have median V in 1.5-4.8 V`);

  let worst = 0;
  for (const rs of byCh.values()) {
    let back = 0;
    for (let k = 1; k < rs.length; k++) if (rs[k].time_s < rs[k - 1].time_s) back++;
    worst = Math.max(worst, rs.length > 1 ? back / (rs.length - 1) : 0);
  }
  add("time increases within each channel", worst <= 0.001, `worst channel has ${(worst * 100).toFixed(2)}% backward time steps${worst <= 0.001 ? "" : " (time format or column wrong?)"}`);

  const votes: number[] = [];
  for (const rs of [...byCh.values()].slice(0, 24)) {
    const imaxCh = Math.max(...rs.map((r) => Math.abs(r.current_a)), 1e-9);
    let agree = 0, n = 0;
    for (let k = 1; k < rs.length; k++) {
      const dv = rs[k].voltage_v - rs[k - 1].voltage_v, i = rs[k].current_a;
      if (Math.abs(i) > 0.02 * imaxCh && Math.abs(dv) > 1e-4) { n++; if (Math.sign(i) === Math.sign(dv)) agree++; }
    }
    if (n > 20) votes.push(agree / n);
  }
  const agree = votes.length ? median(votes) : null;
  add("current sign: positive = charge", agree === null || agree >= 0.6, agree === null ? "no current steps to check"
    : `voltage moves with current sign in ${Math.round(agree * 100)}% of samples${agree >= 0.6 ? "" : "; current looks inverted, set current_sign to discharge_positive"}`);

  const cycleCounts = [...byCh.values()].map((rs) => new Set(rs.map((r) => r.cycle)).size);
  add("cycles labelled", Math.max(...cycleCounts) >= 1 && rows.every((r) => Number.isFinite(r.cycle)), `${Math.min(...cycleCounts)}-${Math.max(...cycleCounts)} cycles per channel`);
  return { checks, ok: checks.every((c) => c.ok), n_channels: byCh.size, n_cycles: Math.max(...cycleCounts), n_rows: rows.length };
}
