/**
 * Browser-side AI commentary ("bring your own key").
 *
 * The static site cannot hold an API key, so a visitor can paste their own
 * Anthropic key; it is kept only in this browser (localStorage, opt-in) and
 * sent only to api.anthropic.com. The prompt and the JSON Claude reviews are
 * the same as the server-side implementation (backend/fintea/model/llm.py).
 */
import type { ModelResponse } from "./types";
import { loadIndex, STATIC } from "./staticMode";

const KEY_STORAGE = "fintea.anthropicKey";
export const DEFAULT_MODEL = "claude-opus-5";

export function loadSavedKey(): string {
  try { return localStorage.getItem(KEY_STORAGE) ?? ""; } catch { return ""; }
}
export function saveKey(key: string, remember: boolean): void {
  try { if (remember && key) localStorage.setItem(KEY_STORAGE, key); else localStorage.removeItem(KEY_STORAGE); } catch { /* ignore */ }
}

const FALLBACK_PROMPT =
  "You are a senior equity research analyst reviewing a DCF and three-statement model built by a junior. " +
  "You receive the model's key outputs, assumptions and rule-based checks as JSON. Write a concise, critical " +
  "qualitative review: (1) the two or three assumptions that matter most and whether they look aggressive, " +
  "conservative or reasonable given the history; (2) what the valuation gap versus the market price most likely " +
  "reflects; (3) specific changes you would make and what evidence you would seek. Use plain language, refer to " +
  "concrete numbers from the JSON, and do not invent data that is not in the JSON. Respond with 5-8 short " +
  "paragraphs or bullet points, no headings, no preamble.";

export function commentaryPayload(m: ModelResponse): Record<string, unknown> {
  const s = m.summary;
  const summary: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(s)) if (k !== "labels" && k !== "error_cells") summary[k] = v;
  return {
    company: s.company, symbol: s.symbol, currency: s.currency, units: s.units, source: s.source,
    summary,
    assumptions: Object.fromEntries(m.assumptions.items.map((i) => [i.key, { value: i.value, basis: i.basis }])),
    checks: m.feedback.quantitative.map((q) => ({ check: q.check, status: q.status, value: q.value })),
    rules_based_narrative: m.feedback.qualitative,
  };
}

export async function generateCommentary(m: ModelResponse, apiKey: string, model = DEFAULT_MODEL): Promise<{ status: string; model?: string; text?: string; error?: string }> {
  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey, dangerouslyAllowBrowser: true, maxRetries: 2 });
  let system = FALLBACK_PROMPT;
  if (STATIC) { try { const idx: any = await loadIndex(); if (idx.commentary_prompt) system = idx.commentary_prompt; } catch { /* keep fallback */ } }
  const messages = [{ role: "user" as const, content: `Model JSON:\n${JSON.stringify(commentaryPayload(m))}` }];
  let response: any;
  try {
    response = await (client.beta.messages as any).create({
      model, max_tokens: 4000, betas: ["server-side-fallback-2026-07-01"], fallbacks: "default",
      system, output_config: { effort: "medium" }, messages,
    });
  } catch (e: any) {
    if (e?.status === 400) {
      response = await client.messages.create({ model, max_tokens: 4000, system, messages });
    } else {
      throw e;
    }
  }
  if (response.stop_reason === "refusal") return { status: "refused", model: response.model, text: "" };
  const text = response.content.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n").trim();
  return { status: "ok", model: response.model, text };
}
