// Generic reader for delimited tester exports, driven by a declarative Mapping that the model proposes.
// No model-written code runs inside Jira: the model only describes the layout; this code applies it.
import type { CanonicalRow } from "./features.ts";

export type Role = "channel_id" | "cycle" | "step" | "time" | "voltage_v" | "current_a" | "temperature_c" | "capacity_ah" | "ignore";
export type TimeFormat = "seconds" | "minutes" | "hours" | "days" | "hh:mm:ss" | "timestamp";
export interface ColumnSpec { source: string; role: Role; scale?: number }
export interface Mapping {
  delimiter: string;
  decimal: "." | ",";
  header_row: number;                 // 0-based line holding the column names
  orientation: "long" | "wide";
  columns?: ColumnSpec[];             // long: one entry per used column
  time_column?: string;               // wide: the shared time column
  voltage_pattern?: string;           // wide: regex with one capture group = channel id, e.g. "^(.+)_V$"
  current_pattern?: string;           // wide: regex with one capture group = channel id
  voltage_scale?: number;
  current_scale?: number;
  time_format: TimeFormat;
  current_sign: "charge_positive" | "discharge_positive";
  single_channel_id?: string | null;  // file holds one cell and no channel column
  confidence?: number;
  notes?: string;
}

export function splitLine(line: string, delimiter: string): string[] {
  return line.split(delimiter).map((s) => s.trim().replace(/^"(.*)"$/, "$1"));
}

export function parseNumber(s: string | undefined, decimal: "." | ","): number {
  if (s === undefined || s === "") return NaN;
  return Number(decimal === "," ? s.replace(",", ".") : s);
}

export function parseTime(raw: string, fmt: TimeFormat, decimal: "." | ","): number {
  switch (fmt) {
    case "seconds": return parseNumber(raw, decimal);
    case "minutes": return parseNumber(raw, decimal) * 60;
    case "hours": return parseNumber(raw, decimal) * 3600;
    case "days": return parseNumber(raw, decimal) * 86400;
    case "hh:mm:ss": {
      const m = raw.match(/^(?:(\d+)\.)?(\d+):(\d+)(?::(\d+(?:[.,]\d+)?))?$/);
      if (!m) return NaN;
      return (+(m[1] ?? 0)) * 86400 + +m[2] * 3600 + +m[3] * 60 + (m[4] ? +m[4].replace(",", ".") : 0);
    }
    case "timestamp": return Date.parse(raw.replace(" ", "T")) / 1000;
  }
}

const threshold = (i: number[]) => Math.max(1e-3, 0.01 * Math.max(0, ...i.map(Math.abs)));

/** Segment numbers from current sign changes (port of vera_helpers.steps_from_current). */
export function stepsFromCurrent(current: number[]): number[] {
  const thr = threshold(current);
  const mode = current.map((x) => (x > thr ? 1 : x < -thr ? -1 : 0));
  let s = 0;
  return mode.map((m, k) => (k === 0 || m !== mode[k - 1] ? ++s : s));
}

/** Cycle index from 1; a new cycle starts at each charge that follows a discharge (positive = charge). */
export function cyclesFromCurrent(current: number[]): number[] {
  const thr = threshold(current);
  let cycle = 1, seenDischarge = false;
  return current.map((x) => {
    if (x < -thr) seenDischarge = true;
    else if (x > thr && seenDischarge) { cycle++; seenDischarge = false; }
    return cycle;
  });
}

function findColumn(header: string[], name: string): number {
  let k = header.indexOf(name);
  if (k < 0) k = header.findIndex((h) => h.toLowerCase() === name.toLowerCase());
  if (k < 0) throw new Error(`column "${name}" not found; header is: ${header.slice(0, 40).join(" | ")}`);
  return k;
}

interface RawRow { id: string; t: number; v: number; i: number; cyc?: number; step?: number }

export function applyMapping(text: string, m: Mapping): CanonicalRow[] {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/);
  if (m.header_row < 0 || m.header_row >= lines.length) throw new Error(`header_row ${m.header_row} is outside the file (${lines.length} lines)`);
  const header = splitLine(lines[m.header_row], m.delimiter);
  const sign = m.current_sign === "discharge_positive" ? -1 : 1;
  const out: RawRow[] = [];

  if (m.orientation === "long") {
    const cols = m.columns ?? [];
    const col = (role: Role) => cols.find((c) => c.role === role);
    for (const need of ["time", "voltage_v", "current_a"] as Role[]) if (!col(need)) throw new Error(`mapping has no column with role "${need}"`);
    if (!col("channel_id") && !m.single_channel_id) throw new Error('mapping needs a "channel_id" column or single_channel_id');
    const idx = (role: Role) => (col(role) ? findColumn(header, col(role)!.source) : -1);
    const [iCh, iT, iV, iI, iC, iS] = (["channel_id", "time", "voltage_v", "current_a", "cycle", "step"] as Role[]).map(idx);
    const sv = col("voltage_v")!.scale ?? 1, si = col("current_a")!.scale ?? 1, st = col("time")!.scale ?? 1;
    for (let k = m.header_row + 1; k < lines.length; k++) {
      if (!lines[k].trim()) continue;
      const f = splitLine(lines[k], m.delimiter);
      if (f.length < header.length - 1) continue;
      const v = parseNumber(f[iV], m.decimal) * sv;
      if (!Number.isFinite(v)) continue;
      out.push({ id: iCh >= 0 ? f[iCh] : String(m.single_channel_id), t: parseTime(f[iT], m.time_format, m.decimal) * st,
        v, i: parseNumber(f[iI], m.decimal) * si * sign,
        cyc: iC >= 0 ? parseNumber(f[iC], m.decimal) : undefined, step: iS >= 0 ? parseNumber(f[iS], m.decimal) : undefined });
    }
  } else {
    if (!m.time_column || !m.voltage_pattern || !m.current_pattern) throw new Error("wide mapping needs time_column, voltage_pattern and current_pattern");
    const iT = findColumn(header, m.time_column);
    const vRe = new RegExp(m.voltage_pattern), iRe = new RegExp(m.current_pattern);
    const chans = new Map<string, { v?: number; i?: number }>();
    header.forEach((h, k) => {
      const mv = h.match(vRe), mi = h.match(iRe);
      if (mv?.[1]) chans.set(mv[1], { ...chans.get(mv[1]), v: k });
      if (mi?.[1]) chans.set(mi[1], { ...chans.get(mi[1]), i: k });
    });
    const pairs = [...chans].filter(([, c]) => c.v !== undefined && c.i !== undefined);
    if (!pairs.length) throw new Error(`no channel matched both patterns; first columns: ${header.slice(0, 12).join(" | ")}`);
    const sv = m.voltage_scale ?? 1, si = m.current_scale ?? 1;
    const byCh = new Map<string, RawRow[]>(pairs.map(([id]) => [id, []]));
    for (let k = m.header_row + 1; k < lines.length; k++) {
      if (!lines[k].trim()) continue;
      const f = splitLine(lines[k], m.delimiter);
      const t = parseTime(f[iT], m.time_format, m.decimal);
      for (const [id, c] of pairs) {
        const v = parseNumber(f[c.v!], m.decimal) * sv;
        if (Number.isFinite(v)) byCh.get(id)!.push({ id, t, v, i: parseNumber(f[c.i!], m.decimal) * si * sign });
      }
    }
    for (const rows of byCh.values()) out.push(...rows);
  }

  // derive cycle and step labels per channel where the file has none
  const byCh = new Map<string, RawRow[]>();
  for (const r of out) { if (!byCh.has(r.id)) byCh.set(r.id, []); byCh.get(r.id)!.push(r); }
  const rows: CanonicalRow[] = [];
  for (const [id, rs] of byCh) {
    const cur = rs.map((r) => r.i);
    const cyc = rs.some((r) => r.cyc === undefined || !Number.isFinite(r.cyc)) ? cyclesFromCurrent(cur) : rs.map((r) => r.cyc!);
    const stp = rs.some((r) => r.step === undefined || !Number.isFinite(r.step)) ? stepsFromCurrent(cur) : rs.map((r) => r.step!);
    rs.forEach((r, k) => rows.push({ channel_id: id, cycle: cyc[k], step: stp[k], time_s: r.t, voltage_v: r.v, current_a: r.i }));
  }
  return rows;
}
