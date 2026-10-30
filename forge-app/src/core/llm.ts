// Nemotron via the NVIDIA API Catalog (OpenAI-compatible). fetch is injected: Forge's fetch in the app, a stub in tests.
export interface Reply { text: string; model: string; role: "planner" | "worker"; tokensIn: number; tokensOut: number; latencyMs: number }
export type Message = { role: "system" | "user" | "assistant"; content: string };
export interface Llm {
  provider: string;
  models: { planner: string; worker: string };
  chat(role: "planner" | "worker", purpose: string, messages: Message[], maxTokens?: number): Promise<Reply>;
}
type FetchFn = (url: string, init?: Record<string, unknown>) => Promise<{ ok: boolean; status: number; json(): Promise<any>; text(): Promise<string>; headers?: { get(k: string): string | null } }>;

export const NVIDIA_BASE = "https://integrate.api.nvidia.com/v1";
const NOT_CHAT = /embed|rerank|reward|guard|safety|retriev|parse|vlm|-vl\b|vision|audio|asr|tts|clip|ocr|omni/i;

export function sizeRank(id: string): number {
  const m = id.toLowerCase();
  const tier = m.includes("ultra") ? 3 : m.includes("super") ? 2 : /nano|lightning|mini/.test(m) ? 0.5 : 1;
  const params = [...m.matchAll(/(\d+(?:\.\d+)?)b(?![a-z])/g)].map((x) => +x[1]);
  return tier * 1000 + (params.length ? Math.max(...params) : 0);
}

export function pickModels(ids: string[]): { planner: string; worker: string } {
  const chat = ids.filter((id) => /nemotron/i.test(id) && !NOT_CHAT.test(id)).sort((a, b) => sizeRank(a) - sizeRank(b));
  if (!chat.length) throw new Error("no Nemotron chat model in the NVIDIA catalog");
  return { planner: chat[chat.length - 1], worker: chat[0] };
}

const THINK = /<think>[\s\S]*?<\/think>/g;

export async function createNvidiaLlm(apiKey: string, fetchFn: FetchFn, onCall?: (r: Reply, purpose: string) => void | Promise<void>): Promise<Llm> {
  const headers = { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" };
  const res = await fetchFn(`${NVIDIA_BASE}/models`, { headers });
  if (!res.ok) throw new Error(`NVIDIA API /models failed: HTTP ${res.status}`);
  const models = pickModels(((await res.json()).data ?? []).map((m: { id: string }) => m.id));
  return {
    provider: "nvidia",
    models,
    async chat(role, purpose, messages, maxTokens = 4096) {
      const t0 = Date.now();
      let delay = 2000;
      for (let attempt = 0; ; attempt++) {
        const r = await fetchFn(`${NVIDIA_BASE}/chat/completions`, { method: "POST", headers,
          body: JSON.stringify({ model: models[role], messages, max_tokens: maxTokens, temperature: 0.2 }) });
        if (r.ok) {
          const j = await r.json();
          const reply: Reply = { text: String(j.choices?.[0]?.message?.content ?? "").replace(THINK, "").trim(), model: models[role], role,
            tokensIn: j.usage?.prompt_tokens ?? 0, tokensOut: j.usage?.completion_tokens ?? 0, latencyMs: Date.now() - t0 };
          await onCall?.(reply, purpose);
          return reply;
        }
        if (![429, 500, 502, 503, 504].includes(r.status) || attempt >= 4) throw new Error(`NVIDIA API chat failed: HTTP ${r.status} ${(await r.text()).slice(0, 300)}`);
        const ra = Number(r.headers?.get("retry-after"));
        await new Promise((ok) => setTimeout(ok, Number.isFinite(ra) && ra > 0 ? ra * 1000 : delay));
        delay = Math.min(delay * 2, 30000);
      }
    },
  };
}

export function firstJsonObject(text: string): unknown {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const src = fenced ? fenced[1] : text;
  const start = src.indexOf("{"), end = src.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("reply contains no JSON object");
  return JSON.parse(src.slice(start, end + 1));
}
