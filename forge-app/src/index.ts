// Forge entry points: issue-panel resolver, background analysis consumer, Rovo actions.
import { fetch } from "@forge/api";
import { Queue } from "@forge/events";
import Resolver from "@forge/resolver";
import { createNvidiaLlm } from "./core/llm.ts";
import { analyseBatch } from "./core/pipeline.ts";
import { createNonconformances, downloadAttachment, listAttachments, postSummaryComment } from "./jira.ts";
import { formatStore, getStatus, listFormats, loadResults, saveResults, setStatus, type RunStatus } from "./store.ts";

const queue = new Queue({ key: "vera-analyse" });
const ISSUE_KEY = /^[A-Z][A-Z0-9_]+-\d+$/;
const LABELS = new Set(["REAL", "REAL+PLANTED", "SYNTHETIC"]);

type AnalyseJob = { issueKey: string; attachmentId: string; filename: string; runId: string; dataLabel: string };

async function startAnalysis(issueKey: string, attachmentName: string | undefined, dataLabel: string): Promise<RunStatus> {
  const current = await getStatus(issueKey);
  if (current && (current.state === "queued" || current.state === "running")) return current;
  const attachments = await listAttachments(issueKey);
  const att = attachmentName ? attachments.find((a) => a.filename === attachmentName || a.id === attachmentName) : attachments[0];
  if (!att) throw new Error(attachmentName ? `no attachment named ${attachmentName} on ${issueKey}` : `no CSV/TSV/TXT attachment on ${issueKey}`);
  const status: RunStatus = { runId: Date.now().toString(36), state: "queued", attachmentId: att.id, filename: att.filename,
    dataLabel: LABELS.has(dataLabel) ? dataLabel : "UNSPECIFIED", startedAt: new Date().toISOString(), events: [] };
  await setStatus(issueKey, status);
  const job: AnalyseJob = { issueKey, attachmentId: att.id, filename: att.filename, runId: status.runId, dataLabel: status.dataLabel };
  await queue.push({ body: job });
  return status;
}

// ---------------------------------------------------------------- background job (up to 900 s)
export async function consumer(event: { body: AnalyseJob }): Promise<void> {
  const job = event.body;
  const status = (await getStatus(job.issueKey)) ?? { runId: job.runId, attachmentId: job.attachmentId, filename: job.filename,
    dataLabel: job.dataLabel, startedAt: new Date().toISOString(), events: [], state: "running" as const };
  status.state = "running";
  await setStatus(job.issueKey, status);
  try {
    const key = process.env.NVIDIA_API_KEY;
    if (!key) throw new Error("NVIDIA_API_KEY is not set (forge variables set --encrypt NVIDIA_API_KEY ...)");
    const text = await downloadAttachment(job.attachmentId);
    const llm = await createNvidiaLlm(key, fetch as never);
    const result = await analyseBatch({ text, filename: job.filename, dataLabel: job.dataLabel, llm, store: formatStore,
      onEvent: async (e) => { status.events.push(e); await setStatus(job.issueKey, status); } });
    await saveResults(job.issueKey, job.runId, result);
    status.state = "done";
  } catch (e) {
    status.state = "failed";
    status.error = (e as Error).message.slice(0, 1000);
  }
  status.finishedAt = new Date().toISOString();
  await setStatus(job.issueKey, status);
}

// ---------------------------------------------------------------- issue panel
const panel = new Resolver();
const issueOf = (context: any): string => {
  const k = context?.extension?.issue?.key;
  if (!k) throw new Error("open Vera from a Jira issue");
  return k;
};
panel.define("getState", async ({ context }) => {
  const issueKey = issueOf(context);
  const [attachments, run, formats] = await Promise.all([listAttachments(issueKey), loadResults(issueKey), listFormats()]);
  return { issueKey, attachments, status: run?.status ?? null, results: run?.results ?? null, formats };
});
panel.define("startAnalysis", async ({ payload, context }) =>
  startAnalysis(issueOf(context), (payload as any).attachmentId, (payload as any).dataLabel));
panel.define("postComment", async ({ context }) => {
  const issueKey = issueOf(context), run = await loadResults(issueKey);
  if (!run?.results) throw new Error("no finished analysis on this issue");
  await postSummaryComment(issueKey, run.results);
  return { ok: true };
});
panel.define("createNcrs", async ({ payload, context }) => {
  const issueKey = issueOf(context), run = await loadResults(issueKey);
  if (!run?.results) throw new Error("no finished analysis on this issue");
  return { keys: await createNonconformances(issueKey, run.results, (payload as any).scope === "flagged" ? "flagged" : "rejected") };
});
export const resolver = panel.getDefinitions();

// ---------------------------------------------------------------- Rovo actions (return JSON; the agent words it)
type ActionPayload = Record<string, any> & { context?: { jira?: { issueKey?: string } } };
const issueFromAction = (p: ActionPayload): string => {
  const k = typeof p.issueKey === "string" && ISSUE_KEY.test(p.issueKey) ? p.issueKey : p.context?.jira?.issueKey;
  if (!k || !ISSUE_KEY.test(String(k))) throw new Error("tell me which Jira issue holds the batch, e.g. QC-12");
  return String(k);
};

export async function actionAnalyse(p: ActionPayload) {
  const s = await startAnalysis(issueFromAction(p), p.attachmentName, p.dataLabel ?? "REAL");
  return { status: s.state, file: s.filename, note: "Vera is analysing in the background; ask for the results in a minute or two." };
}

export async function actionResults(p: ActionPayload) {
  const issueKey = issueFromAction(p), run = await loadResults(issueKey);
  if (!run) return { status: "none", note: `No Vera analysis on ${issueKey} yet.` };
  if (!run.results) return { status: run.status.state, error: run.status.error ?? null, progress: run.status.events.at(-1)?.type ?? null };
  const r = run.results;
  return { status: "done", file: r.source_name, data_label: r.data_label, summary: r.summary, verified_summary: r.narrative,
    flagged: r.channels.filter((c) => c.flags.length).slice(0, 30).map((c) => ({ channel: c.channel_id, grade: c.grade,
      capacity_ah: c.capacity_ah, ir_mohm: c.ir_mohm, flags: c.flags.map((f) => ({ type: f.type, severity: f.severity, ...f.evidence[0] })),
      explanation: c.explanation })),
    note: "All numbers were computed by Vera's code. Quote them exactly; do not compute new ones." };
}

export async function actionExplain(p: ActionPayload) {
  const issueKey = issueFromAction(p), run = await loadResults(issueKey);
  const c = run?.results?.channels.find((x) => x.channel_id.toLowerCase() === String(p.channelId ?? "").toLowerCase());
  if (!c) return { found: false, note: `No channel ${p.channelId} in the latest analysis of ${issueKey}.` };
  return { found: true, ...c, note: "All numbers were computed by Vera's code. Quote them exactly." };
}

export async function actionNcr(p: ActionPayload) {
  const issueKey = issueFromAction(p), run = await loadResults(issueKey);
  if (!run?.results) return { created: [], note: `No finished analysis on ${issueKey}.` };
  const keys = await createNonconformances(issueKey, run.results, p.scope === "flagged" ? "flagged" : "rejected");
  return { created: keys, note: keys.length ? `Created ${keys.length} linked issues.` : "No cells matched." };
}
