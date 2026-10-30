// Jira REST calls used by Vera for Jira. Reads use the app identity; writes use the user's, so issues and comments
// are authored by the person who asked.
import api, { route } from "@forge/api";
import type { BatchResult, ChannelResult } from "./core/pipeline.ts";

export interface Attachment { id: string; filename: string; size: number; created: string }
const TEXT_EXPORT = /\.(csv|tsv|txt|dat)$/i;

export async function listAttachments(issueKey: string): Promise<Attachment[]> {
  const r = await api.asApp().requestJira(route`/rest/api/3/issue/${issueKey}?fields=attachment`);
  if (!r.ok) throw new Error(`could not read ${issueKey}: HTTP ${r.status}`);
  const j = await r.json();
  return (j.fields?.attachment ?? [])
    .filter((a: { filename: string }) => TEXT_EXPORT.test(a.filename))
    .map((a: Attachment) => ({ id: String(a.id), filename: a.filename, size: a.size, created: a.created }))
    .sort((a: Attachment, b: Attachment) => b.created.localeCompare(a.created));
}

export async function downloadAttachment(id: string): Promise<string> {
  const r = await api.asApp().requestJira(route`/rest/api/3/attachment/content/${id}`);
  if (!r.ok) throw new Error(`could not download attachment ${id}: HTTP ${r.status}`);
  return r.text();
}

// ---------------------------------------------------------------- Atlassian Document Format helpers
const text = (t: string, marks?: { type: string }[]) => ({ type: "text", text: t, ...(marks ? { marks } : {}) });
const para = (...content: unknown[]) => ({ type: "paragraph", content });
const heading = (t: string, level = 3) => ({ type: "heading", attrs: { level }, content: [text(t)] });
const bullets = (items: string[]) => ({ type: "bulletList", content: items.map((i) => ({ type: "listItem", content: [para(text(i))] })) });
const doc = (...content: unknown[]) => ({ type: "doc", version: 1, content });

export function evidenceLine(c: ChannelResult): string[] {
  return c.flags.map((f) => {
    const e = f.evidence[0];
    return `${f.type} (${f.severity}): ${e.metric} ${e.value} ${e.unit} vs batch median ${e.batch_median}, ${e.robust_z === null ? e.threshold : `robust z ${e.robust_z}`}`;
  });
}

export async function postSummaryComment(issueKey: string, res: BatchResult): Promise<void> {
  const s = res.summary;
  const flagged = res.channels.filter((c) => c.flags.length).slice(0, 15);
  const body = doc(
    heading(`Vera QC: ${res.source_name} (${res.data_label})`),
    para(text(`${s.n_channels} channels graded: A ${s.grade_counts.A}, B ${s.grade_counts.B}, C ${s.grade_counts.C}, reject ${s.grade_counts.REJECT}. Reference capacity ${s.reference_capacity_ah} Ah.`)),
    ...(res.narrative ? [para(text(res.narrative))] : []),
    ...(flagged.length ? [heading("Flagged cells", 4), bullets(flagged.map((c) => `${c.channel_id} (grade ${c.grade}): ${evidenceLine(c).join("; ")}`))] : []),
    para(text("Every number was computed by Vera's code; model-written sentences were checked against the results.", [{ type: "em" }])),
  );
  const r = await api.asUser().requestJira(route`/rest/api/3/issue/${issueKey}/comment`, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ body }),
  });
  if (!r.ok) throw new Error(`could not comment on ${issueKey}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
}

export async function createNonconformances(issueKey: string, res: BatchResult, scope: "rejected" | "flagged"): Promise<string[]> {
  const issue = await (await api.asApp().requestJira(route`/rest/api/3/issue/${issueKey}?fields=project`)).json();
  const projectId = issue.fields.project.id;
  const types = await (await api.asUser().requestJira(route`/rest/api/3/issue/createmeta/${projectId}/issuetypes`)).json();
  const list = (types.issueTypes ?? types.values ?? []) as { id: string; name: string; subtask: boolean }[];
  const type = list.find((t) => t.name === "Bug") ?? list.find((t) => t.name === "Task") ?? list.find((t) => !t.subtask);
  if (!type) throw new Error("no usable issue type in this project");
  const cells = res.channels.filter((c) => (scope === "flagged" ? c.flags.length > 0 : c.grade === "REJECT"));
  const keys: string[] = [];
  for (const c of cells.slice(0, 50)) {
    const description = doc(
      para(text(`Cell ${c.channel_id} from batch ${issueKey} (${res.source_name}) was graded ${c.grade} by Vera.`)),
      bullets([`Capacity ${c.capacity_ah ?? "n/a"} Ah; internal resistance ${c.ir_mohm ?? "n/a"} mOhm`, ...evidenceLine(c)]),
      ...(c.explanation ? [para(text(c.explanation))] : []),
      para(text("Evidence computed by Vera's code; the explanation was checked against it.", [{ type: "em" }])),
    );
    const r = await api.asUser().requestJira(route`/rest/api/3/issue`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ fields: { project: { id: projectId }, issuetype: { id: type.id }, labels: ["vera-ncr", "cell-qc"],
        summary: `NCR: cell ${c.channel_id} ${c.grade === "REJECT" ? "rejected" : `grade ${c.grade}`} (${c.flags.map((f) => f.type).join(", ") || "capacity bin"})`,
        description } }),
    });
    if (!r.ok) throw new Error(`could not create an issue for ${c.channel_id}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
    const created = await r.json();
    keys.push(created.key);
    await api.asUser().requestJira(route`/rest/api/3/issueLink`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: { name: "Relates" }, inwardIssue: { key: created.key }, outwardIssue: { key: issueKey } }),
    });
  }
  return keys;
}
