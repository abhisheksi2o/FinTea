import { fmtValue } from "../../format";
import type { ChartSpec, DistressVote, RiskInputItem, RiskSummary } from "../../types";

export type Tone = "good" | "warn" | "bad" | "muted";

/** Status colours are reserved for the grade and verdicts (never for chart series). */
export const GRADE_COLORS: Record<string, string> = { Minimal: "#1e7e34", Low: "#5c9e31", Moderate: "#c9971a", High: "#d9661a", Severe: "#c00000" };
export const GRADES: { name: string; from: number; to: number }[] = [
  { name: "Minimal", from: 0, to: 20 }, { name: "Low", from: 20, to: 40 }, { name: "Moderate", from: 40, to: 60 }, { name: "High", from: 60, to: 80 }, { name: "Severe", from: 80, to: 100 },
];
export const gradeColor = (grade: string | null | undefined) => GRADE_COLORS[grade ?? ""] ?? "#5f6b7a";
export const gradeTone = (grade: string | null | undefined): Tone =>
  grade === "Minimal" || grade === "Low" ? "good" : grade === "Moderate" ? "warn" : grade === "High" || grade === "Severe" ? "bad" : "muted";

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const ZERO: Record<string, string> = { pct: "0.0%", pct2: "0.00%", pct4: "0.0000%", mult: "0.0x", num: "0", num1: "0.0", num2: "0.00", int: "0", price: "0.00", score: "0.00", score3: "0.000" };

/** Format a risk number with a leading minus (not accounting parentheses), "0" instead of "-" and "n/a" for null. */
export function fmtRisk(v: unknown, fmt: string, fallback = "n/a"): string {
  if (v === null || v === undefined) return fallback;
  if (typeof v === "string") return v || fallback;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (!isNum(v)) return fallback;
  if (Math.abs(v) < 1e-12) return ZERO[fmt] ?? "0";
  const s = fmtValue(Math.abs(v), fmt);
  return v < 0 ? `-${s}` : s;
}

/** Axis tick formatter: short, clean numbers (values in USD millions get k / m suffixes). */
export function fmtAxis(v: number, fmt: string): string {
  if (!isNum(v)) return "";
  const trim = (x: number) => { const a = Math.abs(x); const d = a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 2; return Number(x.toFixed(d)).toString(); };
  switch (fmt) {
    case "pct": case "pct2": case "pct4": return `${trim(v * 100)}%`;
    case "mult": return `${trim(v)}x`;
    case "int": return String(Math.round(v));
    case "num": case "num1": case "num2": case "price": {
      const a = Math.abs(v), sign = v < 0 ? "-" : "";
      if (a >= 1e6) return `${sign}${trim(a / 1e6)}m`;
      if (a >= 1e4) return `${sign}${trim(a / 1e3)}k`;
      return `${sign}${a.toLocaleString("en-US", { maximumFractionDigits: a >= 100 ? 0 : 1 })}`;
    }
    default: return trim(v);
  }
}

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: iso.length > 10 ? "2-digit" : undefined, minute: iso.length > 10 ? "2-digit" : undefined, timeZone: "UTC" }) + (iso.length > 10 ? " UTC" : "");
};

export function verdictTone(text: string | null | undefined): Tone {
  if (!text) return "muted";
  const t = text.toLowerCase();
  if (/not distressed|no signal/.test(t)) return "good";
  if (/distress|failure|bankrupt|at risk|manipulation|weak|fail/.test(t)) return "bad";
  if (/grey|gray|average|review|watch|caution|flag/.test(t)) return "warn";
  if (/safe|healthy|solvent|strong|pass|verified/.test(t)) return "good";
  return "muted";
}

export function ratingTone(r: string | null | undefined): Tone {
  if (!r) return "muted";
  const u = r.toUpperCase();
  if (/^(AAA|AA|A|BBB)/.test(u)) return "good";
  if (/^(BB|B)/.test(u)) return "warn";
  return "bad";
}

export function zoneTone(zone: string | null | undefined): Tone { return verdictTone(zone); }

export function piotroskiTone(f: number | null | undefined): Tone { return f == null ? "muted" : f >= 7 ? "good" : f >= 4 ? "warn" : "bad"; }

export function pdTone(pd: number | null | undefined): Tone { return pd == null ? "muted" : pd < 0.01 ? "good" : pd < 0.1 ? "warn" : "bad"; }

export const seriesOf = (s: RiskSummary, key: string): (number | null)[] => {
  const arr = s.series?.[key];
  return Array.isArray(arr) ? (arr as unknown[]).map((v) => (isNum(v) ? v : null)) : [];
};

export interface ModelRow { key: string; model: string; seriesKey: string | null; fmt: string; latest: number | null; verdict: string | null; tone: Tone; vote?: DistressVote; group: string; note?: string }

export function modelRows(s: RiskSummary, votes: DistressVote[]): ModelRow[] {
  const vote = (name: string) => votes.find((v) => v.model === name);
  const rows: ModelRow[] = [
    { key: "z", model: "Altman Z (1968, market equity)", seriesKey: "altman_z", fmt: "score", latest: s.altman_z, verdict: s.altman_zone ? `${s.altman_zone} zone` : null, tone: zoneTone(s.altman_zone), group: "Altman family" },
    { key: "z1", model: "Altman Z' (1983, book equity)", seriesKey: "altman_z1", fmt: "score", latest: s.altman_z1, verdict: s.altman_z1_zone ? `${s.altman_z1_zone} zone` : null, tone: zoneTone(s.altman_z1_zone), group: "Altman family" },
    { key: "z2", model: "Altman Z'' (1995, non-manufacturers / emerging markets)", seriesKey: "altman_z2", fmt: "score", latest: s.altman_z2, verdict: s.altman_z2_zone ? `${s.altman_z2_zone} zone` : null, tone: zoneTone(s.altman_z2_zone), vote: vote("Altman Z''"), group: "Altman family" },
    { key: "em", model: "EM score (Z'' + 3.25) rating equivalent", seriesKey: "em_score", fmt: "score", latest: s.em_score, verdict: s.em_rating, tone: ratingTone(s.em_rating), group: "Altman family" },
    { key: "ohlson_o", model: "Ohlson O-score (1980, logit)", seriesKey: "ohlson_o", fmt: "score", latest: s.ohlson_o, verdict: s.ohlson_flag, tone: verdictTone(s.ohlson_flag), vote: vote("Ohlson"), group: "Probability models" },
    { key: "ohlson_pd", model: "Ohlson probability of distress", seriesKey: "ohlson_pd", fmt: "pct", latest: s.ohlson_pd, verdict: null, tone: pdTone(s.ohlson_pd), group: "Probability models" },
    { key: "zmij", model: "Zmijewski X-score (1984, probit)", seriesKey: null, fmt: "score", latest: s.zmijewski_x, verdict: s.zmijewski_flag, tone: verdictTone(s.zmijewski_flag), vote: vote("Zmijewski"), group: "Probability models" },
    { key: "zmij_pd", model: "Zmijewski probability of distress", seriesKey: "zmijewski_pd", fmt: "pct", latest: s.zmijewski_pd, verdict: null, tone: pdTone(s.zmijewski_pd), group: "Probability models" },
    { key: "springate", model: "Springate S-score (1978)", seriesKey: "springate", fmt: "score", latest: s.springate, verdict: s.springate_flag, tone: verdictTone(s.springate_flag), vote: vote("Springate"), group: "Other discriminant models" },
    { key: "grover", model: "Grover G-score (2001)", seriesKey: "grover", fmt: "score", latest: s.grover, verdict: s.grover_flag, tone: verdictTone(s.grover_flag), vote: vote("Grover"), group: "Other discriminant models" },
    { key: "taffler", model: "Taffler Z (1983, UK)", seriesKey: "taffler", fmt: "score", latest: s.taffler, verdict: s.taffler_flag, tone: verdictTone(s.taffler_flag), vote: vote("Taffler"), group: "Other discriminant models" },
    { key: "pio", model: "Piotroski F-score (0-9, financial strength)", seriesKey: "piotroski", fmt: "int", latest: s.piotroski, verdict: s.piotroski_class, tone: piotroskiTone(s.piotroski), group: "Earnings quality", note: s.has_prior_year ? undefined : "needs a prior fiscal year" },
    { key: "beneish", model: "Beneish M-score (earnings-quality signal, not a default model)", seriesKey: "beneish_m", fmt: "score", latest: s.beneish_m, verdict: s.beneish_flag, tone: verdictTone(s.beneish_flag), group: "Earnings quality", note: s.has_prior_year ? undefined : "needs a prior fiscal year" },
  ];
  return rows;
}

/** Verdict rows for the overview table (one line per model, including the market-based ones). */
export function verdictRows(s: RiskSummary, votes: DistressVote[]) {
  const v = (name: string) => votes.find((x) => x.model === name)?.distress;
  return [
    { model: "Altman Z''", value: fmtRisk(s.altman_z2, "score"), verdict: s.altman_z2_zone ? `${s.altman_z2_zone} zone` : "n/a", tone: zoneTone(s.altman_z2_zone), distress: v("Altman Z''") },
    { model: "Ohlson O", value: s.ohlson_pd == null ? "n/a" : `PD ${fmtRisk(s.ohlson_pd, "pct")}`, verdict: s.ohlson_flag ?? "n/a", tone: verdictTone(s.ohlson_flag), distress: v("Ohlson") },
    { model: "Zmijewski X", value: s.zmijewski_pd == null ? "n/a" : `PD ${fmtRisk(s.zmijewski_pd, "pct")}`, verdict: s.zmijewski_flag ?? "n/a", tone: verdictTone(s.zmijewski_flag), distress: v("Zmijewski") },
    { model: "Springate", value: fmtRisk(s.springate, "score"), verdict: s.springate_flag ?? "n/a", tone: verdictTone(s.springate_flag), distress: v("Springate") },
    { model: "Grover", value: fmtRisk(s.grover, "score"), verdict: s.grover_flag ?? "n/a", tone: verdictTone(s.grover_flag), distress: v("Grover") },
    { model: "Taffler", value: fmtRisk(s.taffler, "score"), verdict: s.taffler_flag ?? "n/a", tone: verdictTone(s.taffler_flag), distress: v("Taffler") },
    { model: "Merton naive DD", value: s.dd_naive == null ? "n/a" : `${fmtRisk(s.dd_naive, "score")} sd`, verdict: s.pd_merton_naive == null ? "n/a" : `PD ${fmtRisk(s.pd_merton_naive, "pct2")}`, tone: pdTone(s.pd_merton_naive), distress: v("Merton naive DD") },
    { model: "Synthetic rating", value: s.synthetic_rating ?? "n/a", verdict: s.default_spread == null ? "n/a" : `spread ${fmtRisk(s.default_spread, "pct2")}`, tone: ratingTone(s.synthetic_rating), distress: undefined },
    { model: "Piotroski F", value: s.piotroski == null ? "n/a" : `${fmtRisk(s.piotroski, "int")} / 9`, verdict: s.piotroski_class ?? "n/a", tone: piotroskiTone(s.piotroski), distress: undefined },
    { model: "Beneish M (earnings quality)", value: fmtRisk(s.beneish_m, "score"), verdict: s.beneish_flag ?? "n/a", tone: verdictTone(s.beneish_flag), distress: undefined },
  ];
}

export const SUB_SCORE_LABELS: Record<string, { label: string; weightKey: string }> = {
  sig_z2: { label: "Altman Z'' (zone-scaled)", weightKey: "w_z2" },
  sig_merton: { label: "Merton naive probability of default", weightKey: "w_merton" },
  sig_ohlson: { label: "Ohlson O-score", weightKey: "w_ohlson" },
  sig_rating: { label: "Synthetic rating", weightKey: "w_rating" },
  sig_zmij: { label: "Zmijewski X-score", weightKey: "w_zmijewski" },
  sig_pio: { label: "Piotroski F-score (inverted)", weightKey: "w_piotroski" },
  sig_cons: { label: "Springate / Grover / Taffler flags", weightKey: "w_consensus" },
};

export const inputValue = (items: RiskInputItem[], key: string): number | null => { const it = items.find((i) => i.key === key); return it && isNum(it.value) ? it.value : null; };

/** Light clean-up of chart specs for the browser (the Excel spec repeats a category for the 1y / 5y rating default rates). */
export function tidyChart(c: ChartSpec, s: RiskSummary): ChartSpec {
  if (!c.categories) return c;
  const seen = new Map<string, number>();
  const categories = c.categories.map((cat) => {
    const k = String(cat ?? "");
    const n = (seen.get(k) ?? 0) + 1; seen.set(k, n);
    if (n === 1) return cat;
    return c.id === "pd_models" ? `${k} (5-year)` : `${k} (${n})`;
  });
  if (c.id === "pd_models") {
    const i1 = categories.findIndex((cat) => String(cat).startsWith("Synthetic rating") && !String(cat).endsWith("(5-year)"));
    if (i1 >= 0 && categories.some((cat) => String(cat).endsWith("(5-year)"))) categories[i1] = `${categories[i1]} (1-year)`;
  }
  void s;
  return { ...c, categories };
}

export const titleCase = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);

/** The summary field that tells whether a distress model could be computed (null = not available). */
const VOTE_FIELD: Record<string, keyof RiskSummary> = { "Altman Z''": "altman_z2", Ohlson: "ohlson_pd", Zmijewski: "zmijewski_pd", Springate: "springate", Grover: "grover", Taffler: "taffler", "Merton naive DD": "dd_naive" };
export interface VoteRow { model: string; state: "distress" | "clear" | "na"; detail: string }
export function voteRows(s: RiskSummary, votes: DistressVote[]): VoteRow[] {
  const detail: Record<string, string> = {
    "Altman Z''": s.altman_z2_zone ? `${fmtRisk(s.altman_z2, "score")} - ${s.altman_z2_zone} zone` : "n/a",
    Ohlson: s.ohlson_pd == null ? "n/a" : `PD ${fmtRisk(s.ohlson_pd, "pct")}`,
    Zmijewski: s.zmijewski_pd == null ? "n/a" : `PD ${fmtRisk(s.zmijewski_pd, "pct")}`,
    Springate: s.springate_flag ?? "n/a", Grover: s.grover_flag ?? "n/a", Taffler: s.taffler_flag ?? "n/a",
    "Merton naive DD": s.dd_naive == null ? "n/a" : `DD ${fmtRisk(s.dd_naive, "score")} sd`,
  };
  return votes.map((v) => {
    const field = VOTE_FIELD[v.model];
    const available = field ? isNum(s[field]) : true;
    return { model: v.model, state: !available ? "na" : v.distress ? "distress" : "clear", detail: detail[v.model] ?? "" };
  });
}

export function applicabilityTone(status: string, missing: string[]): Tone {
  const t = status.toLowerCase();
  if (t.startsWith("applicable with") || (t.startsWith("applicable") && missing.length > 0)) return "warn";
  if (t.startsWith("applicable")) return "good";
  return "muted";
}

export const SUB_SCORE_SHORT: Record<string, string> = { sig_z2: "Altman Z''", sig_merton: "Merton PD", sig_ohlson: "Ohlson", sig_rating: "Rating", sig_zmij: "Zmijewski", sig_pio: "Piotroski", sig_cons: "Springate / Grover / Taffler" };
const SUB_ORDER = ["sig_z2", "sig_merton", "sig_ohlson", "sig_rating", "sig_zmij", "sig_pio", "sig_cons"];

/** Horizontal bar chart of the seven sub-scores (0 = minimal ... 100 = severe) behind the distress signal index. */
export function subScoreSpec(s: RiskSummary): ChartSpec {
  const keys = SUB_ORDER.filter((k) => k in (s.sub_scores ?? {}));
  return {
    id: "sub_scores", type: "bar", title: "Distress signal index: sub-score by signal", fmt: "num1", y_title: "0 = minimal ... 100 = severe", x_title: "",
    stacked: false, y_min: 0, y_max: 100, note: "Each signal is rescaled to 0-100 and weighted (weights on the Inputs tab). The index is an uncalibrated ranking device, not a probability of default.", anchor: "",
    categories: keys.map((k) => SUB_SCORE_SHORT[k] ?? k),
    series: [{ name: "Sub-score", color: "2E75B6", values: keys.map((k) => { const v = (s.sub_scores as unknown as Record<string, unknown>)[k]; return isNum(v) ? v : null; }) }],
  };
}

export interface StressRow { scenario: string; shock: string; result: string; tone: Tone; base: string }
export function stressRows(s: RiskSummary): StressRow[] {
  const st = s.stress;
  if (!st) return [];
  const pct = (v: number | null) => (v == null ? "n/a" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(0)}%`);
  return [
    { scenario: "Market equity falls", shock: pct(st.equity_shock), result: `PD ${fmtRisk(st.pd_equity_shock, "pct2")}`, tone: pdTone(st.pd_equity_shock), base: `PD ${fmtRisk(s.pd_merton_naive, "pct2")}` },
    { scenario: "Equity volatility rises", shock: pct(st.vol_shock), result: `PD ${fmtRisk(st.pd_vol_shock, "pct2")}`, tone: pdTone(st.pd_vol_shock), base: `PD ${fmtRisk(s.pd_merton_naive, "pct2")}` },
    { scenario: "Both shocks together", shock: `${pct(st.equity_shock)} / ${pct(st.vol_shock)}`, result: `PD ${fmtRisk(st.pd_both, "pct2")}`, tone: pdTone(st.pd_both), base: `PD ${fmtRisk(s.pd_merton_naive, "pct2")}` },
    { scenario: "EBIT falls (Altman Z'')", shock: pct(st.ebit_shock), result: `Z'' ${fmtRisk(st.z2_ebit_shock, "score")}${st.z2_ebit_zone ? ` - ${st.z2_ebit_zone} zone` : ""}`, tone: zoneTone(st.z2_ebit_zone), base: `Z'' ${fmtRisk(s.altman_z2, "score")}${s.altman_z2_zone ? ` - ${s.altman_z2_zone}` : ""}` },
  ];
}
