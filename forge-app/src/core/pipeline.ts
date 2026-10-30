// One Vera for Jira analysis: export text in, graded and explained batch out. Platform-free (no Forge imports), so it
// runs the same in tests and in the Forge consumer. Mirrors agent/pipeline.py with a declarative mapping instead of code.
import { channelFeatures, type Curve, type CycleRow } from "./features.ts";
import { DEFAULT_THRESHOLDS, gradeChannel, referenceCapacity, type Grade, type Thresholds } from "./grading.ts";
import { firstJsonObject, type Llm, type Message } from "./llm.ts";
import { median } from "./numeric.ts";
import { fingerprint, peekForPrompt, peekText } from "./peek.ts";
import * as P from "./prompts.ts";
import { applyMapping, type Mapping } from "./reader.ts";
import { detect, RULES, type Flag } from "./rules.ts";
import { validate } from "./validate.ts";
import { badNumbers, factsFrom, splitSentences, withPercentages } from "./verify.ts";

export interface FormatStore {
  get(fp: string): Promise<{ mapping: Mapping; saved_at: string; learned_from: string } | undefined>;
  set(fp: string, rec: { mapping: Mapping; saved_at: string; learned_from: string }): Promise<void>;
}
export interface VeraEvent { seq: number; ts: string; type: string; [k: string]: unknown }
export interface ChannelResult {
  channel_id: string; position: [number, number]; grade: Grade; capacity_ah: number | null; ir_mohm: number | null;
  flags: Flag[]; explanation: string | null; cycles: CycleRow[];
}
export interface BatchResult {
  data_label: string; source_name: string; fingerprint: string; mapping: Mapping; thresholds: Thresholds;
  summary: { n_channels: number; n_flagged: number; grade_counts: Record<Grade, number>; flag_counts: Record<string, number>;
    reference_capacity_ah: number; median_ir_mohm: number | null };
  channels: ChannelResult[]; curves: Record<string, Record<number, Curve>>; narrative: string; report: string;
  verify: { claims_checked: number; claims_failed: number; sentences_regenerated: number; sentences_dropped: number };
  models: { planner: string; worker: string }; provider: string;
}

const MAX_ATTEMPTS = 4;

export function positions(ids: string[]): Record<string, [number, number]> {
  const m = ids.map((i) => i.match(/^([A-Za-z])(\d{1,3})$/));
  if (m.every(Boolean)) return Object.fromEntries(ids.map((id, k) => [id, [m[k]![1].toUpperCase().charCodeAt(0) - 65, +m[k]![2] - 1]]));
  const cols = Math.max(1, Math.ceil(Math.sqrt(ids.length)));
  return Object.fromEntries(ids.map((id, k) => [id, [Math.floor(k / cols), k % cols]]));
}

export async function analyseBatch(opts: {
  text: string; filename: string; dataLabel: string; llm: Llm; store: FormatStore;
  onEvent?: (e: VeraEvent) => void | Promise<void>; thresholds?: Thresholds;
}): Promise<BatchResult> {
  const { text, filename, llm, store } = opts;
  const th = opts.thresholds ?? DEFAULT_THRESHOLDS;
  const t0 = Date.now();
  let seq = 0;
  const emit = async (type: string, body: Record<string, unknown> = {}) =>
    opts.onEvent?.({ seq: seq++, ts: new Date().toISOString(), type, ...body });
  const verify = { claims_checked: 0, claims_failed: 0, sentences_regenerated: 0, sentences_dropped: 0 };
  let tokens = 0;
  const chat = async (role: "planner" | "worker", purpose: string, messages: Message[], max = 3000) => {
    const r = await llm.chat(role, purpose, messages, max);
    tokens += r.tokensIn + r.tokensOut;
    await emit("llm.call", { role, model: r.model, purpose, tokens_in: r.tokensIn, tokens_out: r.tokensOut, latency_ms: r.latencyMs, cost_usd: 0 });
    return r.text;
  };

  await emit("run.started", { source: { kind: "upload", name: filename, size_bytes: text.length, data_label: opts.dataLabel },
    mode: "live", runner: "forge", models: llm.models, provider: llm.provider });

  // ---------------------------------------------------------------- ingestion: memory, then mapping with repair
  const peek = peekText(filename, text);
  const fp = await fingerprint(peek);
  let mapping: Mapping | null = null;
  let rows = null as ReturnType<typeof applyMapping> | null;

  const attempt = async (m: Mapping, n: number): Promise<string | null> => {
    await emit("schema.proposed", { tier: "declarative", attempt: n, mapping: m });
    let r;
    try { r = applyMapping(text, m); } catch (e) { return `The reader could not apply the mapping: ${(e as Error).message}`; }
    const v = validate(r);
    await emit("schema.validated", { ok: v.ok, checks: v.checks, n_channels: v.n_channels, n_cycles: v.n_cycles, n_rows: v.n_rows });
    if (!v.ok) return `The table failed validation:\n${v.checks.filter((c) => !c.ok).map((c) => `- ${c.name}: ${c.detail}`).join("\n")}`;
    mapping = m; rows = r;
    return null;
  };

  const saved = await store.get(fp);
  if (saved) {
    await emit("memory.hit", { kind: "mapping", fingerprint: fp, saved_at: saved.saved_at, learned_from: saved.learned_from });
    await attempt(saved.mapping, 1);
  }
  const messages: Message[] = [{ role: "system", content: P.PLANNER_SYSTEM }, { role: "user", content: P.mappingPrompt(filename, peekForPrompt(peek)) }];
  for (let n = 1; !rows && n <= MAX_ATTEMPTS; n++) {
    const reply = await chat("planner", n === 1 ? "describe the layout of an unfamiliar file" : "repair the layout description", messages, 2500);
    let candidate: unknown = null, problem: string | null;
    try { candidate = firstJsonObject(reply); problem = await attempt(P.parseMapping(candidate), n); } catch (e) { problem = (e as Error).message; }
    if (problem && n < MAX_ATTEMPTS) {
      await emit("repair.attempt", { attempt: n, max_attempts: MAX_ATTEMPTS - 1, error_summary: problem.split("\n").slice(-1)[0].slice(0, 300) });
      messages.push({ role: "assistant", content: reply }, { role: "user", content: P.repairPrompt(candidate, problem) });
    }
  }
  if (!rows || !mapping) {
    await emit("run.failed", { stage: "ingest", error: `no valid layout after ${MAX_ATTEMPTS} attempts` });
    throw new Error(`Vera could not read ${filename} after ${MAX_ATTEMPTS} attempts`);
  }
  if (!saved || saved.mapping !== mapping) await store.set(fp, { mapping, saved_at: new Date().toISOString(), learned_from: filename });

  // ---------------------------------------------------------------- analysis (deterministic)
  const { features, cycles, curves } = channelFeatures(rows);
  const ids = features.map((f) => f.channel_id);
  await emit("analysis.progress", { done: ids.length, total: ids.length, unit: "channels" });
  const feats = Object.fromEntries(RULES.map(([name]) => [name, features.map((f) => (f as unknown as Record<string, number | null>)[name])]));
  const flags = detect(ids, feats);
  const ref = referenceCapacity(features.map((f) => f.capacity_ah), th);
  const irs = features.filter((f) => f.ir_mohm !== null && !flags[f.channel_id].some((x) => x.type === "NOISY_OR_DEAD_CHANNEL")).map((f) => f.ir_mohm as number);
  const medIr = irs.length ? median(irs) : null;
  const pos = positions(ids);
  const channels: ChannelResult[] = features.map((f) => ({ channel_id: f.channel_id, position: pos[f.channel_id],
    grade: gradeChannel(f.capacity_ah, f.ir_mohm, flags[f.channel_id], ref, medIr, th), capacity_ah: f.capacity_ah,
    ir_mohm: f.ir_mohm, flags: flags[f.channel_id], explanation: null, cycles: cycles[f.channel_id] }));
  const gradeCounts = { A: 0, B: 0, C: 0, REJECT: 0 } as Record<Grade, number>;
  const flagCounts: Record<string, number> = {};
  for (const c of channels) { gradeCounts[c.grade]++; for (const f of c.flags) flagCounts[f.type] = (flagCounts[f.type] ?? 0) + 1; }
  const summary = { n_channels: channels.length, n_flagged: channels.filter((c) => c.flags.length).length, grade_counts: gradeCounts,
    flag_counts: flagCounts, reference_capacity_ah: Math.round(ref * 1e5) / 1e5, median_ir_mohm: medIr === null ? null : Math.round(medIr * 1e4) / 1e4 };
  await emit("results.ready", { summary });

  // ---------------------------------------------------------------- worker text, every number verified
  const verified = async (txt: string, facts: Set<number>, fixFacts: unknown) => {
    const kept: string[] = [];
    for (const s of splitSentences(txt)) {
      verify.claims_checked++;
      const bad = badNumbers(s, facts, ids);
      if (!bad.length) { kept.push(s); continue; }
      verify.claims_failed++;
      const fixed = (await chat("worker", "regenerate sentence that failed verification",
        [{ role: "system", content: P.WORKER_SYSTEM }, { role: "user", content: P.fixSentencePrompt(s, bad, fixFacts) }], 400)).trim();
      const still = badNumbers(fixed, facts, ids);
      await emit("verify.claim_failed", { sentence: s.slice(0, 500), claim: bad.join(", "), reason: "number not found in computed results", action: still.length ? "dropped" : "regenerated" });
      if (still.length) verify.sentences_dropped++; else { verify.sentences_regenerated++; kept.push(fixed); }
    }
    return kept.join(" ");
  };
  const byType = new Map<string, Record<string, unknown>[]>();
  for (const c of channels) for (const f of c.flags) {
    if (!byType.has(f.type)) byType.set(f.type, []);
    byType.get(f.type)!.push({ channel_id: c.channel_id, grade: c.grade, ...f.evidence[0] });
  }
  const explained = new Map<string, string[]>();
  for (const [fault, all] of [...byType].sort((a, b) => b[1].length - a[1].length)) {
    const sample = all.sort((a, b) => Math.abs((b.robust_z as number) ?? 99) - Math.abs((a.robust_z as number) ?? 99)).slice(0, 8);
    let parsed: Record<string, string> = {};
    try { parsed = (firstJsonObject(await chat("worker", `explain ${fault} flags`, [{ role: "system", content: P.WORKER_SYSTEM },
      { role: "user", content: P.explainPrompt(fault, sample) }], 1500)) as { explanations: Record<string, string> }).explanations ?? {}; } catch { parsed = {}; }
    for (const r of sample) {
      const id = r.channel_id as string, txt = parsed[id];
      if (typeof txt === "string" && txt.trim()) {
        const ok = await verified(txt, withPercentages(factsFrom(r), []), r);
        if (ok) explained.set(id, [...(explained.get(id) ?? []), ok]);
      }
    }
  }
  for (const c of channels) c.explanation = explained.get(c.channel_id)?.join(" ") ?? null;
  const notable = channels.filter((c) => c.flags.length)
    .sort((a, b) => Math.max(...b.flags.map((f) => Math.abs(f.evidence[0].robust_z ?? 99))) - Math.max(...a.flags.map((f) => Math.abs(f.evidence[0].robust_z ?? 99)))).slice(0, 6);
  const facts = { channels_graded: summary.n_channels, channels_flagged: summary.n_flagged, grade_counts: gradeCounts, flag_counts: flagCounts,
    reference_capacity_ah: Math.round(ref * 1000) / 1000, median_ir_mohm: medIr === null ? null : Math.round(medIr * 100) / 100, data_label: opts.dataLabel,
    most_important_channels: notable.map((c) => ({ channel_id: c.channel_id, grade: c.grade, flags: c.flags.map((f) => ({ type: f.type,
      metric: f.evidence[0].metric, value: f.evidence[0].value, unit: f.evidence[0].unit, batch_median: f.evidence[0].batch_median })) })) };
  const narrative = await verified(await chat("worker", "write QC report summary", [{ role: "system", content: P.WORKER_SYSTEM },
    { role: "user", content: P.narrativePrompt(facts) }], 1200), withPercentages(factsFrom(facts), [summary.n_channels, summary.n_flagged]), facts);
  await emit("verify.summary", verify);

  const flaggedCurves = Object.fromEntries(channels.filter((c) => c.flags.length).slice(0, 24).map((c) => [c.channel_id, curves[c.channel_id]]));
  const report = buildReport(filename, opts.dataLabel, llm, summary, channels, narrative, verify);
  await emit("report.ready", { formats: ["md"] });
  await emit("run.finished", { duration_s: (Date.now() - t0) / 1000, tokens });
  return { data_label: opts.dataLabel, source_name: filename, fingerprint: fp, mapping, thresholds: th, summary, channels,
    curves: flaggedCurves, narrative, report, verify, models: llm.models, provider: llm.provider };
}

function buildReport(name: string, label: string, llm: Llm, s: BatchResult["summary"], channels: ChannelResult[], narrative: string, v: BatchResult["verify"]): string {
  const lines = [`# Vera QC report: ${name}`, "", `Data: **${label}** · planner \`${llm.models.planner}\`, worker \`${llm.models.worker}\` (${llm.provider})`, "",
    "## Summary", "", narrative || "_The summary was removed because it failed number verification._", "",
    "## Grades", "", `Reference capacity ${s.reference_capacity_ah} Ah; median internal resistance ${s.median_ir_mohm ?? "n/a"} mOhm.`, "",
    "| Grade | Channels |", "|---|---|", ...(Object.entries(s.grade_counts).map(([g, n]) => `| ${g} | ${n} |`)), "",
    "## Flagged channels", "", "| Channel | Grade | Flag | Evidence |", "|---|---|---|---|"];
  for (const c of channels) for (const f of c.flags) {
    const e = f.evidence[0];
    lines.push(`| ${c.channel_id} | ${c.grade} | ${f.type} (${f.severity}) | ${e.metric} ${e.value} ${e.unit} vs median ${e.batch_median} (${e.robust_z === null ? e.threshold : `z ${e.robust_z}`}) |`);
  }
  lines.push("", `Every number above was computed by code. ${v.claims_checked} model-written sentences were checked; ${v.claims_failed} failed, ${v.sentences_regenerated} regenerated, ${v.sentences_dropped} dropped.`);
  return lines.join("\n");
}
