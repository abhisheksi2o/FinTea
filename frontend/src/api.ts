import type { ModelResponse, Provider, RiskResponse, SearchResult } from "./types";
import { STATIC, staticBuild, staticProviders, staticRebuild, staticSearch } from "./staticMode";

export const REPO_URL = "https://github.com/abhisheksi2o/FinTea";
export const STATIC_RISK_NOTICE =
  "Default risk analysis needs the full FinTea app: it fetches statements, prices and rates live, solves the Merton model and verifies the Excel report with LibreOffice, none of which can run on GitHub Pages.";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try { const js = await res.json(); detail = typeof js.detail === "string" ? js.detail : JSON.stringify(js.detail); } catch { /* ignore */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const live = {
  providers: () => fetch("/api/providers").then((r) => json<{ providers: Provider[]; default: string }>(r)),
  health: () => fetch("/api/health").then((r) => json<{ status: string; libreoffice: boolean; llm_enabled: boolean }>(r)),
  search: (q: string, provider: string, signal?: AbortSignal) =>
    fetch(`/api/search?q=${encodeURIComponent(q)}&provider=${encodeURIComponent(provider)}`, { signal }).then((r) => json<{ results: SearchResult[] }>(r)),
  build: (query: string, provider: string, years: number) =>
    post("/api/models", { query, provider, years, overrides: {}, verify: true }).then((r) => json<ModelResponse>(r)),
  rebuild: (_base: ModelResponse, id: string, overrides: Record<string, unknown>, years?: number) =>
    post(`/api/models/${id}/rebuild`, { overrides, years, verify: true }).then((r) => json<ModelResponse>(r)),
  /** Default risk analysis: Altman / Ohlson / Zmijewski / Piotroski / Beneish / Merton / synthetic rating + verified Excel report. */
  risk: (query: string, provider: string) =>
    post("/api/risk", { query, provider, overrides: {}, verify: true, include_sheets: true }).then((r) => json<RiskResponse>(r)),
  riskRebuild: (id: string, overrides: Record<string, unknown>) =>
    post(`/api/risk/${id}/rebuild`, { overrides, verify: true, include_sheets: true }).then((r) => json<RiskResponse>(r)),
};

const stat: typeof live = {
  providers: async () => ({ providers: staticProviders, default: "static" }),
  health: async () => ({ status: "ok", libreoffice: false, llm_enabled: false }),
  search: async (q: string, _provider: string, _signal?: AbortSignal) => ({ results: await staticSearch(q) }),
  build: (query: string, _provider: string, _years: number) => staticBuild(query),
  rebuild: async (base: ModelResponse, _id: string, overrides: Record<string, unknown>, _years?: number) => staticRebuild(base, overrides),
  risk: (_query: string, _provider: string) => Promise.reject(new Error(STATIC_RISK_NOTICE)),
  riskRebuild: (_id: string, _overrides: Record<string, unknown>) => Promise.reject(new Error(STATIC_RISK_NOTICE)),
};

export const api = STATIC ? stat : live;
export { STATIC };
