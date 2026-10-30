// Port of agent/verify.py: every number in model-written text must match a number computed by code.
const NUM = /(?<![\w.])[-+]?\d+(?:[.,]\d+)?%?/g;

export function factsFrom(obj: unknown, out = new Set<number>()): Set<number> {
  if (typeof obj === "number" && Number.isFinite(obj)) out.add(obj);
  else if (Array.isArray(obj)) obj.forEach((v) => factsFrom(v, out));
  else if (obj && typeof obj === "object") Object.values(obj).forEach((v) => factsFrom(v, out));
  return out;
}

export function withPercentages(facts: Set<number>, totals: number[]): Set<number> {
  const extra = new Set(facts);
  for (const t of totals) if (t) for (const f of facts) if (f >= 0 && f <= t && Number.isInteger(f)) extra.add((100 * f) / t);
  for (const f of facts) if (f !== 0 && Math.abs(f) < 1.5) extra.add(100 * f);
  return extra;
}

export function badNumbers(sentence: string, facts: Set<number>, channelIds: string[]): string[] {
  let text = sentence;
  for (const id of [...channelIds].sort((a, b) => b.length - a.length)) {
    text = text.replace(new RegExp(`(?<![\\w])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w])`, "g"), " ");
  }
  const bad: string[] = [];
  for (const m of text.matchAll(NUM)) {
    const s = m[0].replace(/%$/, "").replace(",", ".");
    const x = Number(s);
    if (!Number.isFinite(x)) continue;
    const dec = s.includes(".") ? s.split(".")[1].length : 0;
    const tol = 0.5 * 10 ** -dec + 1e-9;
    if (![...facts].some((f) => Math.abs(x - f) <= tol || (f !== 0 && Math.abs(x - f) / Math.abs(f) <= 0.005))) bad.push(m[0]);
  }
  return bad;
}

export function splitSentences(text: string): string[] {
  return text.trim().split(/(?<=[.!?])\s+(?=[A-Z0-9"(])/).map((s) => s.trim()).filter(Boolean);
}
