import React, { useCallback, useEffect, useMemo, useState } from "react";
import ForgeReconciler, {
  Box, Button, ButtonGroup, DynamicTable, Heading, Inline, Label, Lozenge, ProgressBar, SectionMessage, Select, Spinner, Stack,
  Strong, Text, Textfield, Tooltip, xcss,
} from "@forge/react";
import { invoke } from "@forge/bridge";
import { DEFAULT_THRESHOLDS, gradeChannel, referenceCapacity, type Grade, type Thresholds } from "../core/grading.ts";
import type { BatchResult } from "../core/pipeline.ts";

const GRADE_BG: Record<Grade, string> = {
  A: "color.background.accent.green.subtle", B: "color.background.accent.blue.subtle",
  C: "color.background.accent.orange.subtle", REJECT: "color.background.accent.red.bolder",
};
const FAULT: Record<string, string> = {
  LOW_CAPACITY: "Low capacity", HIGH_IR: "High resistance", CURVE_SHAPE: "Curve shape", CAPACITY_CREEP_UP: "Capacity creep",
  LOW_CE: "Low first-cycle CE", NOISY_OR_DEAD_CHANNEL: "Noisy or dead",
};
const STEP: Record<string, string> = {
  "run.started": "Started", "memory.hit": "Recognised a learned layout", "llm.call": "Nemotron call", "schema.proposed": "Layout proposed",
  "schema.validated": "Checked units, voltage, time, current sign, cycles", "repair.attempt": "Self-repair", "analysis.progress": "Features computed",
  "results.ready": "Cells flagged and graded", "verify.claim_failed": "Rejected a sentence with an unsupported number",
  "verify.summary": "Report numbers verified", "report.ready": "Report ready", "run.finished": "Done",
};

function Tray({ res, grades }: { res: BatchResult; grades: Grade[] }) {
  const rows = new Map<number, { id: string; grade: Grade; flagged: boolean; tip: string }[]>();
  res.channels.forEach((c, k) => {
    const [r] = c.position;
    if (!rows.has(r)) rows.set(r, []);
    rows.get(r)!.push({ id: c.channel_id, grade: grades[k], flagged: c.flags.length > 0,
      tip: `${c.channel_id}: grade ${grades[k]}, ${c.capacity_ah ?? "n/a"} Ah${c.flags.length ? ", " + c.flags.map((f) => FAULT[f.type]).join(", ") : ""}` });
  });
  return (
    <Stack space="space.025">
      {[...rows.keys()].sort((a, b) => a - b).map((r) => (
        <Inline key={String(r)} space="space.025">
          {rows.get(r)!.map((cell) => (
            <Tooltip key={cell.id} content={cell.tip}>
              <Box xcss={xcss({ backgroundColor: GRADE_BG[cell.grade] as any, width: "26px", height: "26px", borderRadius: "radius.small" })}>
                <Inline alignInline="center" alignBlock="center">
                  <Text size="small">{cell.grade === "REJECT" ? "R" : cell.grade}{cell.flagged ? "•" : ""}</Text>
                </Inline>
              </Box>
            </Tooltip>
          ))}
        </Inline>
      ))}
    </Stack>
  );
}

function App() {
  const [state, setState] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<string | null>(null);
  const [label, setLabel] = useState("REAL");
  const [th, setTh] = useState<Thresholds>(DEFAULT_THRESHOLDS);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setState(await invoke("getState")); setError(null); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const running = state?.status && (state.status.state === "queued" || state.status.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [running, load]);

  const res: BatchResult | null = state?.results ?? null;
  const grades = useMemo(() => {
    if (!res) return [];
    try {
      const ref = referenceCapacity(res.channels.map((c) => c.capacity_ah), th);
      return res.channels.map((c) => gradeChannel(c.capacity_ah, c.ir_mohm, c.flags, ref, res.summary.median_ir_mohm, th));
    } catch { return res.channels.map((c) => c.grade); }
  }, [res, th]);
  const counts = useMemo(() => grades.reduce((m, g) => ({ ...m, [g]: (m[g] ?? 0) + 1 }), {} as Record<string, number>), [grades]);

  if (error) return <SectionMessage appearance="error" title="Vera could not load"><Text>{error}</Text></SectionMessage>;
  if (!state) return <Spinner label="Loading Vera" />;

  const start = async () => {
    setNotice(null);
    try { await invoke("startAnalysis", { attachmentId: attachment ?? state.attachments[0]?.id, dataLabel: label }); await load(); }
    catch (e) { setNotice((e as Error).message); }
  };
  const act = async (fn: string, payload = {}) => {
    try { const r: any = await invoke(fn, payload); setNotice(r.keys ? `Created ${r.keys.length} issues: ${r.keys.join(", ") || "none matched"}` : "Summary posted as a comment."); }
    catch (e) { setNotice((e as Error).message); }
  };
  const flagged = res ? res.channels.map((c, k) => ({ c, g: grades[k] })).filter((x) => x.c.flags.length) : [];

  return (
    <Stack space="space.200">
      <Text>Attach a formation or grading tester export (CSV, TSV or semicolon text) to this issue. Vera reads the layout with
        NVIDIA Nemotron, checks it with code, computes every number with code, and explains the flags.</Text>
      {state.attachments.length === 0 ? (
        <SectionMessage appearance="information" title="No tester export attached"><Text>Attach a .csv, .tsv or .txt export to this issue, then reopen Vera.</Text></SectionMessage>
      ) : (
        <Inline space="space.100" alignBlock="end">
          <Stack space="space.050"><Label labelFor="att">Export</Label>
            <Select inputId="att" options={state.attachments.map((a: any) => ({ label: `${a.filename} (${Math.round(a.size / 1024)} kB)`, value: a.id }))}
              defaultValue={{ label: state.attachments[0].filename, value: state.attachments[0].id }} onChange={(o: any) => setAttachment(o.value)} /></Stack>
          <Stack space="space.050"><Label labelFor="lbl">Data is</Label>
            <Select inputId="lbl" options={["REAL", "SYNTHETIC"].map((v) => ({ label: v, value: v }))} defaultValue={{ label: "REAL", value: "REAL" }}
              onChange={(o: any) => setLabel(o.value)} /></Stack>
          <Button appearance="primary" onClick={start} isDisabled={!!running}>{running ? "Analysing…" : "Analyse"}</Button>
        </Inline>
      )}
      {notice && <SectionMessage appearance="information"><Text>{notice}</Text></SectionMessage>}
      {state.status && (running || state.status.state === "failed") && (
        <Stack space="space.100">
          {running && <ProgressBar ariaLabel="Analysis progress" isIndeterminate />}
          {state.status.state === "failed" && <SectionMessage appearance="error" title="Analysis failed"><Text>{state.status.error}</Text></SectionMessage>}
          {state.status.events.slice(-8).map((e: any) => (
            <Text key={String(e.seq)}>{STEP[e.type] ?? e.type}{e.type === "llm.call" ? `: ${e.purpose} (${e.model})` : ""}{e.type === "repair.attempt" ? `: ${e.error_summary}` : ""}</Text>
          ))}
        </Stack>
      )}
      {res && (
        <Stack space="space.200">
          <Heading size="small">{res.source_name} · {res.summary.n_channels} channels · {res.data_label}</Heading>
          <Inline space="space.100">
            <Lozenge appearance="success">A {counts.A ?? 0}</Lozenge><Lozenge appearance="inprogress">B {counts.B ?? 0}</Lozenge>
            <Lozenge appearance="moved">C {counts.C ?? 0}</Lozenge><Lozenge appearance="removed">Reject {counts.REJECT ?? 0}</Lozenge>
            <Text>Reference {res.summary.reference_capacity_ah} Ah · median IR {res.summary.median_ir_mohm ?? "n/a"} mΩ</Text>
          </Inline>
          <Tray res={res} grades={grades} />
          {res.narrative && <Text>{res.narrative}</Text>}
          <DynamicTable caption="Flagged cells (evidence computed by code)" rowsPerPage={10}
            head={{ cells: ["Cell", "Grade", "Flag", "Evidence", "Explanation"].map((k) => ({ key: k, content: k })) }}
            rows={flagged.map(({ c, g }) => ({ key: c.channel_id, cells: [
              { key: "c", content: c.channel_id }, { key: "g", content: g },
              { key: "f", content: c.flags.map((f) => FAULT[f.type]).join(", ") },
              { key: "e", content: c.flags.map((f) => { const e = f.evidence[0]; return `${e.metric} ${e.value} ${e.unit} vs ${e.batch_median}${e.robust_z === null ? "" : ` (z ${e.robust_z})`}`; }).join("; ") },
              { key: "x", content: c.explanation ?? "" }] }))} />
          <Stack space="space.050">
            <Strong>Grade bins (regrading runs instantly in code, no model call)</Strong>
            <Inline space="space.100">
              {(["A", "B", "C"] as const).map((g) => (
                <Stack key={g} space="space.025"><Label labelFor={`cap${g}`}>{g}: capacity ≥ %</Label>
                  <Textfield id={`cap${g}`} type="number" defaultValue={String(th.capacity_min_pct[g])}
                    onChange={(e: any) => setTh({ ...th, capacity_min_pct: { ...th.capacity_min_pct, [g]: Number(e.target.value) } })} /></Stack>
              ))}
            </Inline>
          </Stack>
          <ButtonGroup label="Actions">
            <Button onClick={() => act("createNcrs", { scope: "rejected" })}>Create NCR issues for rejects</Button>
            <Button onClick={() => act("createNcrs", { scope: "flagged" })}>NCRs for all flagged</Button>
            <Button onClick={() => act("postComment")}>Post summary comment</Button>
          </ButtonGroup>
          <Text size="small">Report: {res.verify.claims_checked} model-written sentences checked, {res.verify.claims_failed} failed,
            {" "}{res.verify.sentences_regenerated} regenerated, {res.verify.sentences_dropped} dropped. Planner {res.models.planner}, worker {res.models.worker}.</Text>
        </Stack>
      )}
      {state.formats?.length > 0 && <Text size="small">Learned layouts: {state.formats.map((f: any) => f.learned_from).join(", ")}</Text>}
    </Stack>
  );
}

ForgeReconciler.render(<React.StrictMode><App /></React.StrictMode>);
