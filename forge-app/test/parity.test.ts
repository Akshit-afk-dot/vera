// The TypeScript engine must reproduce the Python engine: same features (within rounding), same flags, same grades.
// Fixture: scripts/make_parity_fixture.py (SYNTHETIC batch, 16 channels, planted faults).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { channelFeatures, type CanonicalRow } from "../src/core/features.ts";
import { detect, RULES } from "../src/core/rules.ts";
import { DEFAULT_THRESHOLDS, gradeChannel, referenceCapacity } from "../src/core/grading.ts";
import { median } from "../src/core/numeric.ts";

const dir = new URL("./fixtures/", import.meta.url);
const expected = JSON.parse(readFileSync(new URL("expected.json", dir), "utf8"));

export function loadCanonicalCsv(text: string): CanonicalRow[] {
  const lines = text.trim().split("\n");
  return lines.slice(1).map((l) => {
    const [channel_id, cycle, step, time_s, voltage_v, current_a] = l.split(",");
    return { channel_id, cycle: +cycle, step: +step, time_s: +time_s, voltage_v: +voltage_v, current_a: +current_a };
  });
}

const rows = loadCanonicalCsv(gunzipSync(readFileSync(new URL("batch.csv.gz", dir))).toString("utf8"));
const { features, cycles } = channelFeatures(rows);
const ids = features.map((f) => f.channel_id);

const close = (a: number | null, b: number | null, tol: number, what: string) => {
  if (a === null || b === null) return assert.equal(a, b, what);
  assert.ok(Math.abs(a - b) <= tol, `${what}: ts ${a} vs py ${b}`);
};

test("same channels and cycles", () => {
  assert.deepEqual(ids, Object.keys(expected.features));
  for (const id of ids) assert.equal(cycles[id].length, expected.cycles[id].length, id);
});

test("features match the Python engine", () => {
  for (const f of features) {
    const e = expected.features[f.channel_id];
    close(f.capacity_ah, e.capacity_ah, 2e-5, `${f.channel_id} capacity`);
    close(f.ir_mohm, e.ir_mohm, 2e-3, `${f.channel_id} ir`);
    close(f.first_cycle_ce, e.first_cycle_ce, 2e-5, `${f.channel_id} ce`);
    close(f.capacity_slope_pct_per_cycle, e.capacity_slope_pct_per_cycle, 2e-4, `${f.channel_id} slope`);
    close(f.noise_mv, e.noise_mv, 1e-3, `${f.channel_id} noise`);
    close(f.curve_dist_pct, e.curve_dist_pct, 1e-3, `${f.channel_id} curve`);
    close(f.dqdv_peak_v, e.dqdv_peak_v, 0.0021, `${f.channel_id} dqdv peak`);
    close(f.mid_voltage_v, e.mid_voltage_v, 1e-4, `${f.channel_id} mid V`);
  }
});

test("flags and grades match the Python engine", () => {
  const feats = Object.fromEntries(RULES.map(([name]) => [name, features.map((f) => (f as unknown as Record<string, number | null>)[name])]));
  const flags = detect(ids, feats);
  for (const id of ids) assert.deepEqual(flags[id].map((f) => ({ type: f.type, severity: f.severity })), expected.flags[id], id);

  const th = DEFAULT_THRESHOLDS;
  const ref = referenceCapacity(features.map((f) => f.capacity_ah), th);
  close(ref, expected.reference_capacity_ah, 2e-5, "reference capacity");
  const noisy = new Set(ids.filter((id) => flags[id].some((f) => f.type === "NOISY_OR_DEAD_CHANNEL")));
  const medIr = median(features.filter((f) => !noisy.has(f.channel_id) && f.ir_mohm !== null).map((f) => f.ir_mohm as number));
  close(medIr, expected.median_ir_mohm, 2e-3, "median IR");
  for (const f of features) {
    assert.equal(gradeChannel(f.capacity_ah, f.ir_mohm, flags[f.channel_id], ref, medIr, th), expected.grades[f.channel_id], f.channel_id);
  }
});
