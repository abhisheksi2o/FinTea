import type { ModelResponse, Provider, SearchResult } from "./types";
import { STATIC, staticBuild, staticProviders, staticRebuild, staticSearch } from "./staticMode";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try { const js = await res.json(); detail = typeof js.detail === "string" ? js.detail : JSON.stringify(js.detail); } catch { /* ignore */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const live = {
  providers: () => fetch("/api/providers").then((r) => json<{ providers: Provider[]; default: string }>(r)),
  health: () => fetch("/api/health").then((r) => json<{ status: string; libreoffice: boolean; llm_enabled: boolean }>(r)),
  search: (q: string, provider: string) =>
    fetch(`/api/search?q=${encodeURIComponent(q)}&provider=${encodeURIComponent(provider)}`).then((r) => json<{ results: SearchResult[] }>(r)),
  build: (query: string, provider: string, years: number) =>
    fetch("/api/models", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, provider, years, overrides: {}, verify: true }) }).then((r) => json<ModelResponse>(r)),
  rebuild: (_base: ModelResponse, id: string, overrides: Record<string, unknown>, years?: number) =>
    fetch(`/api/models/${id}/rebuild`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides, years, verify: true }) }).then((r) => json<ModelResponse>(r)),
};

const stat = {
  providers: async () => ({ providers: staticProviders, default: "static" }),
  health: async () => ({ status: "ok", libreoffice: false, llm_enabled: false }),
  search: async (q: string, _provider: string) => ({ results: await staticSearch(q) }),
  build: (query: string, _provider: string, _years: number) => staticBuild(query),
  rebuild: async (base: ModelResponse, _id: string, overrides: Record<string, unknown>, _years?: number) => staticRebuild(base, overrides),
};

export const api = STATIC ? stat : live;
export { STATIC };
