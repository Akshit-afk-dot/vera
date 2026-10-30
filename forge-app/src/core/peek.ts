// Structural peek of a text export (what the model sees) and a layout fingerprint (format memory).
// Ports of agent/ingest/peek.py (text branch) and agent/ingest/checks.py.

const MAX_LINE = 400;

export function sniffDelimiter(lines: string[]): string | null {
  const body = lines.filter((l) => l.trim()).slice(-20);
  let best: { score: [number, number]; d: string } | null = null;
  for (const d of [",", ";", "\t", "|"]) {
    const counts = new Map<number, number>();
    for (const l of body) { const c = l.split(d).length - 1; counts.set(c, (counts.get(c) ?? 0) + 1); }
    let mode = 0, freq = 0;
    for (const [c, n] of counts) if (n > freq) { mode = c; freq = n; }
    if (mode === 0) continue;
    const score: [number, number] = [freq / body.length, mode];
    if (!best || score[0] > best.score[0] || (score[0] === best.score[0] && score[1] > best.score[1])) best = { score, d };
  }
  return best ? best.d : null;
}

export interface TextPeek { name: string; bytes: number; kind: "text"; sniffed_delimiter: string | null; total_lines: number; first_lines: string[] }

export function peekText(name: string, text: string, nLines = 30): TextPeek {
  const all = text.replace(/^﻿/, "").split(/\r?\n/);
  const first = all.slice(0, nLines);
  return { name, bytes: text.length, kind: "text", sniffed_delimiter: sniffDelimiter(first), total_lines: all.length, first_lines: first };
}

/** What the planner sees: wide lines are trimmed, but their field count and last fields are reported. */
export function peekForPrompt(p: TextPeek): string {
  const delim = p.sniffed_delimiter ?? ",";
  const wide = p.first_lines.some((l) => l.length > MAX_LINE);
  const lines = p.first_lines.slice(0, wide ? 12 : 30).map((l) => {
    if (l.length <= MAX_LINE) return l;
    const f = l.split(delim);
    return `${l.slice(0, MAX_LINE)} ... [line has ${f.length} fields; last 4: ${f.slice(-4).join(delim)}]`;
  });
  return JSON.stringify({ ...p, first_lines: lines }, null, 1);
}

const ID_LIKE = /[A-Za-z]{0,4}\d+/g;

export async function fingerprint(p: TextPeek): Promise<string> {
  const delim = p.sniffed_delimiter ?? ",";
  const nonNumeric = (l: string) => l.split(delim).filter((t) => t && !/^[-+\d.,:\s]+$/.test(t)).length;
  const header = p.first_lines.reduce((a, b) => (nonNumeric(b) > nonNumeric(a) ? b : a), "");
  const toks = new Set(header.split(/[\s,;\t|]+/).filter((t) => t && !/^[-+]?[\d.,:]+$/.test(t)).map((t) => t.replace(ID_LIKE, "#").toLowerCase()));
  const sig = `text|${delim}|${[...toks].sort().join("|")}`;
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(sig));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
}
