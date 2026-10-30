// Forge-edition pipeline end to end with a scripted model: a unit mistake is caught and repaired, an invented
// number is caught by the verifier, a second file in the same layout is read from memory, and a wide export works.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import type { Llm, Message } from "../src/core/llm.ts";
import { analyseBatch, type FormatStore, type VeraEvent } from "../src/core/pipeline.ts";
import { applyMapping, type Mapping } from "../src/core/reader.ts";
import { validate } from "../src/core/validate.ts";

const dir = new URL("./fixtures/", import.meta.url);
const read = (f: string) => gunzipSync(readFileSync(new URL(f, dir))).toString("utf8");
const expected = JSON.parse(readFileSync(new URL("expected.json", dir), "utf8"));
const LONG = read("export_long.csv.gz"), WIDE = read("export_wide.csv.gz");

const GOOD_LONG: Mapping = {
  delimiter: ";", decimal: ",", header_row: 3, orientation: "long", time_format: "hh:mm:ss", current_sign: "charge_positive",
  columns: [{ source: "Chan", role: "channel_id" }, { source: "Cyc", role: "cycle" }, { source: "Stp", role: "step" },
    { source: "Test Time", role: "time", scale: 1 }, { source: "Volts (mV)", role: "voltage_v", scale: 0.001 },
    { source: "Amps (mA)", role: "current_a", scale: 0.001 }, { source: "Temp (C)", role: "temperature_c", scale: 1 }],
};
const BUGGY_LONG: Mapping = { ...GOOD_LONG, columns: GOOD_LONG.columns!.map((c) => (c.role === "voltage_v" ? { ...c, scale: 1 } : c)) };
const WIDE_MAP: Mapping = { delimiter: ",", decimal: ".", header_row: 0, orientation: "wide", time_column: "elapsed_min", time_format: "minutes",
  voltage_pattern: "^(.+)_V$", current_pattern: "^(.+)_I$", voltage_scale: 1, current_scale: 1, current_sign: "charge_positive" };

function scripted(calls: string[], first: Mapping, second?: Mapping): Llm {
  let planner = 0;
  return {
    provider: "scripted", models: { planner: "scripted-planner", worker: "scripted-worker" },
    async chat(role, purpose, messages: Message[]) {
      calls.push(purpose);
      let text: string;
      if (role === "planner") text = JSON.stringify(planner++ === 0 ? first : (second ?? first));
      else if (purpose.startsWith("explain")) {
        const rows = JSON.parse(messages[1].content.match(/\(JSON\):\n(\[[\s\S]*\])\n\nFor each/)![1]);
        text = JSON.stringify({ explanations: Object.fromEntries(rows.map((r: any) => [r.channel_id, `${r.metric} is ${r.value} ${r.unit} against a batch median of ${r.batch_median}.`])) });
      } else if (purpose.startsWith("write QC")) {
        const facts = JSON.parse(messages[1].content.split("(JSON):\n")[1].split("\n\nWrite")[0]);
        text = `Vera graded ${facts.channels_graded} channels. The batch median capacity was 9.99 Ah. ${facts.channels_flagged} channels were flagged.`;
      } else text = "The batch median capacity is shown in the grade table.";
      return { text, model: role === "planner" ? "scripted-planner" : "scripted-worker", role, tokensIn: 10, tokensOut: 5, latencyMs: 1 };
    },
  };
}

function memoryStore(): FormatStore {
  const m = new Map();
  return { async get(fp) { return m.get(fp); }, async set(fp, rec) { m.set(fp, rec); } };
}

test("reader + validation accept the semicolon export only with the right units", () => {
  assert.equal(validate(applyMapping(LONG, GOOD_LONG)).ok, true);
  const bad = validate(applyMapping(LONG, BUGGY_LONG));
  assert.equal(bad.ok, false);
  assert.ok(bad.checks.some((c) => c.name.startsWith("units") && !c.ok));
});

test("pipeline repairs, verifies, remembers", async () => {
  const store = memoryStore(), calls: string[] = [], events: VeraEvent[] = [];
  const res = await analyseBatch({ text: LONG, filename: "export_long.csv", dataLabel: "SYNTHETIC", llm: scripted(calls, BUGGY_LONG, GOOD_LONG),
    store, onEvent: (e) => { events.push(e); } });
  const types = events.map((e) => e.type);
  assert.equal(types[0], "run.started");
  assert.equal(types.at(-1), "run.finished");
  assert.ok(types.includes("repair.attempt"));
  assert.equal(res.summary.n_channels, 16);
  const flagged = res.channels.filter((c) => c.flags.length).map((c) => c.channel_id).sort();
  const expectedFlagged = Object.entries(expected.flags).filter(([, f]) => (f as unknown[]).length).map(([id]) => id).sort();
  assert.deepEqual(flagged, expectedFlagged);
  assert.ok(!res.report.includes("9.99"));
  assert.equal(res.verify.claims_failed, 1);
  assert.equal(res.verify.sentences_regenerated, 1);

  const calls2: string[] = [], events2: VeraEvent[] = [];
  await analyseBatch({ text: LONG, filename: "next_batch.csv", dataLabel: "SYNTHETIC", llm: scripted(calls2, GOOD_LONG), store,
    onEvent: (e) => { events2.push(e); } });
  assert.ok(events2.some((e) => e.type === "memory.hit"));
  assert.ok(!calls2.some((c) => c.startsWith("describe")));
});

test("wide export: no cycle or step columns, cycles derived from current", async () => {
  const rows = applyMapping(WIDE, WIDE_MAP);
  const v = validate(rows);
  assert.equal(v.ok, true, JSON.stringify(v.checks));
  assert.equal(v.n_channels, 16);
  assert.equal(v.n_cycles, 4);
  const res = await analyseBatch({ text: WIDE, filename: "export_wide.csv", dataLabel: "SYNTHETIC", llm: scripted([], WIDE_MAP), store: memoryStore() });
  for (const c of res.channels) {
    const e = expected.features[c.channel_id].capacity_ah;
    if (e > 0.5) assert.ok(Math.abs((c.capacity_ah as number) - e) / e < 0.01, `${c.channel_id} ${c.capacity_ah} vs ${e}`);
  }
});
