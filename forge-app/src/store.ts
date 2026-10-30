// Forge Key-Value Store layout. One value is at most 240 KiB, so results, curves and report live under separate keys.
import { kvs } from "@forge/kvs";
import type { BatchResult, FormatStore, VeraEvent } from "./core/pipeline.ts";
import type { Mapping } from "./core/reader.ts";

export interface RunStatus {
  runId: string; state: "queued" | "running" | "done" | "failed"; attachmentId: string; filename: string;
  dataLabel: string; startedAt: string; finishedAt?: string; error?: string; events: VeraEvent[];
}

export const formatStore: FormatStore = {
  async get(fp) { return (await kvs.get(`fmt:${fp}`)) as { mapping: Mapping; saved_at: string; learned_from: string } | undefined; },
  async set(fp, rec) { await kvs.set(`fmt:${fp}`, rec); },
};

export async function listFormats(): Promise<{ fingerprint: string; learned_from: string; saved_at: string }[]> {
  const { WhereConditions } = await import("@forge/kvs");
  const page = await kvs.query().where("key", WhereConditions.beginsWith("fmt:")).limit(50).getMany();
  return page.results.map((r: { key: string; value: any }) => ({ fingerprint: r.key.slice(4), learned_from: r.value.learned_from, saved_at: r.value.saved_at }));
}

export const getStatus = async (issueKey: string) => (await kvs.get(`run:${issueKey}`)) as RunStatus | undefined;
export const setStatus = (issueKey: string, s: RunStatus) => kvs.set(`run:${issueKey}`, { ...s, events: s.events.slice(-60) });

export async function saveResults(issueKey: string, runId: string, res: BatchResult): Promise<void> {
  const { curves, report, ...rest } = res;
  await kvs.set(`res:${issueKey}:${runId}`, rest);
  await kvs.set(`cur:${issueKey}:${runId}`, curves);
  await kvs.set(`rep:${issueKey}:${runId}`, report);
}

export async function loadResults(issueKey: string): Promise<{ status: RunStatus; results?: BatchResult } | undefined> {
  const status = await getStatus(issueKey);
  if (!status) return undefined;
  if (status.state !== "done") return { status };
  const [rest, curves, report] = await Promise.all([kvs.get(`res:${issueKey}:${status.runId}`), kvs.get(`cur:${issueKey}:${status.runId}`), kvs.get(`rep:${issueKey}:${status.runId}`)]);
  return { status, results: rest ? ({ ...(rest as object), curves: curves ?? {}, report: report ?? "" } as BatchResult) : undefined };
}
