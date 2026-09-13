/**
 * Static (GitHub Pages) mode: models are pre-built JSON files; assumption edits are
 * recalculated in the browser by the formula engine; edited workbooks are written
 * client-side with ExcelJS.
 */
import { Engine } from "./engine";
import type { AssumptionItem, ModelResponse, Provider, QuantCheck, SearchResult, Sheet } from "./types";

export const STATIC = import.meta.env.VITE_STATIC === "1";

export interface IndexEntry { symbol: string; name: string; currency: string; price: number; implied_price: number; upside: number; wacc: number; status: string; verification: string; cells_checked: number; provider: string; generated: string; json: string; xlsx: string }
export interface SiteIndex { generated: string; models: IndexEntry[]; failures: { symbol: string; error: string }[] }

let indexCache: SiteIndex | null = null;
export async function loadIndex(): Promise<SiteIndex> {
  if (indexCache) return indexCache;
  const r = await fetch("index.json", { cache: "no-cache" });
  if (!r.ok) throw new Error("index.json not found - the static site has not been built");
  indexCache = (await r.json()) as SiteIndex;
  return indexCache;
}

export const staticProviders: Provider[] = [{ id: "static", name: "Pre-built models (refreshed nightly from Yahoo Finance)", description: "", available: true, requires: "", reason: "" }];

export async function staticSearch(q: string): Promise<SearchResult[]> {
  const idx = await loadIndex();
  const s = q.trim().toLowerCase();
  return idx.models.filter((m) => m.symbol.toLowerCase().includes(s) || m.name.toLowerCase().includes(s))
    .map((m) => ({ symbol: m.symbol, name: m.name, exchange: m.currency, type: "EQUITY" })).slice(0, 10);
}

export async function staticBuild(query: string): Promise<ModelResponse> {
  const idx = await loadIndex();
  const q = query.trim().toLowerCase();
  const hit = idx.models.find((m) => m.symbol.toLowerCase() === q) ?? idx.models.find((m) => m.symbol.toLowerCase().includes(q) || m.name.toLowerCase().includes(q));
  if (!hit) throw new Error(`"${query}" is not among the ${idx.models.length} pre-built companies on this static site. Run FinTea locally (see the GitHub repository) to build any listed company live.`);
  const r = await fetch(hit.json, { cache: "no-cache" });
  if (!r.ok) throw new Error(`could not load ${hit.json}`);
  return (await r.json()) as ModelResponse;
}

/** Apply overrides to the Assumptions sheet, recalculate everything in the browser and refresh summary + checks. */
export function staticRebuild(base: ModelResponse, overrides: Record<string, unknown>): ModelResponse {
  const model: ModelResponse = JSON.parse(JSON.stringify(base));
  const sheets = model.sheets!;
  const asm = sheets.find((s) => s.name === "Assumptions")!;
  const nh = model.meta.nh as number;
  const items = model.assumptions.items;
  for (const [key, raw] of Object.entries(overrides)) {
    const item = items.find((i) => i.key === key);
    if (!item) continue;
    const cells = asm.rows.flatMap((r) => r.cells.filter((c) => c.k === key));
    if (item.kind === "scalar") {
      const v = Number(raw);
      item.value = v; item.overridden = true;
      for (const c of cells) c.v = v;
    } else {
      const vals = Array.isArray(raw) ? raw.map(Number) : [Number(raw)];
      const arr = [...(item.value as number[])].map((x, j) => vals[Math.min(j, vals.length - 1)] ?? x);
      item.value = arr; item.overridden = true;
      cells.filter((c) => c.c >= asm.period_cols[String(nh)]).sort((a, b) => a.c - b.c).forEach((c, j) => { c.v = arr[j]; });
    }
    if (!item.basis.startsWith("User override")) item.basis = "User override (recalculated in the browser). " + item.basis;
  }
  const eng = new Engine(sheets);
  eng.recalculate();
  refreshSummary(model, eng);
  model.id = base.id + "-edited";
  model.download_url = "";
  (model as any).client_generated = true;
  (model as any).parent_id = base.id;
  return model;
}

function refreshSummary(model: ModelResponse, eng: Engine) {
  const g = (sheet: string, key: string): any => { const c = eng.keyed(sheet, key)[0]; return c ? c.v : null; };
  const labels: string[] = model.meta.labels; const last = labels.length - 1; const nh = model.meta.nh as number;
  const isSheet = model.sheets!.find((s) => s.name === "Income Statement")!;
  const lastCol = isSheet.period_cols[String(last)];
  const isKey = (key: string, col: number) => { for (const row of isSheet.rows) for (const c of row.cells) if (c.k === key && c.c === col) return c.v; return null; };
  Object.assign(model.summary, {
    implied_price: g("DCF", "implied_price"), upside: g("DCF", "upside"), enterprise_value: g("DCF", "enterprise_value"),
    equity_value: g("DCF", "equity_value"), wacc: g("WACC", "wacc"), cost_of_equity: g("WACC", "cost_of_equity"),
    raw_beta: g("Beta", "raw_beta"), selected_beta: g("Beta", "selected_beta"), r_squared: g("Beta", "r_squared"),
    tv_share: g("DCF", "tv_share"), overall_status: g("Feedback", "overall_status"), n_fail: g("Feedback", "n_fail"),
    n_flag: g("Feedback", "n_flag"), altman_z: g("Feedback", "altman_z"), piotroski: g("Feedback", "piotroski"),
    price: g("Assumptions", "price"), terminal_growth: g("Assumptions", "terminal_growth"),
    revenue_terminal: isKey("revenue", lastCol), ebitda_margin_terminal: isKey("m_ebitda_margin", lastCol),
    revenue_base: isKey("revenue", isSheet.period_cols[String(nh - 1)]),
  });
  const fb = model.sheets!.find((s) => s.name === "Feedback")!;
  const checks: QuantCheck[] = [];
  for (const row of fb.rows) {
    const byCol = new Map(row.cells.map((c) => [c.c, c]));
    const st = byCol.get(4);
    if (st?.k?.endsWith("_status")) checks.push({ check: String(byCol.get(1)?.v ?? ""), value: typeof byCol.get(2)?.v === "number" ? (byCol.get(2)!.v as number) : null, fmt: byCol.get(2)?.fmt ?? "general", threshold: String(byCol.get(3)?.v ?? ""), status: String(st.v), why: String(byCol.get(5)?.v ?? "") });
  }
  model.feedback.quantitative = checks;
  model.feedback.status = String(model.summary.overall_status);
  model.feedback.n_fail = Number(model.summary.n_fail); model.feedback.n_flag = Number(model.summary.n_flag);
  model.verification = { status: "browser", reason: "recalculated in the browser by FinTea's formula engine", cells_checked: 0, mismatches: [] } as any;
}

// ------------------------------------------------------------- xlsx export
const FORMATS: Record<string, string> = {
  num: '#,##0;(#,##0);"-"', num1: '#,##0.0;(#,##0.0);"-"', num2: '#,##0.00;(#,##0.00);"-"', pct: '0.0%;(0.0%);"-"', pct2: '0.00%;(0.00%);"-"',
  mult: '0.0"x";(0.0"x");"-"', price: "#,##0.00", int: "#,##0", days: "0.0", date: "dd-mmm-yyyy", text: "@", general: "General", factor: "0.0000", beta: "0.000",
};
const NAVY = "FF1F3864";
function colLetter(c: number): string { let s = ""; while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); } return s; }

export async function exportWorkbook(model: ModelResponse): Promise<Blob> {
  const ExcelJS = await import("exceljs");
  const wb = new ExcelJS.Workbook();
  wb.creator = "FinTea"; wb.calcProperties.fullCalcOnLoad = true;
  const named: Record<string, [string, string]> = { WACC: ["WACC", "wacc"], ImpliedSharePrice: ["DCF", "implied_price"], EnterpriseValue: ["DCF", "enterprise_value"], SelectedBeta: ["Beta", "selected_beta"], TerminalGrowth: ["Assumptions", "terminal_growth"], TaxRate: ["Assumptions", "tax_rate"] };
  for (const sh of model.sheets as Sheet[]) {
    const ws = wb.addWorksheet(sh.name, { properties: { tabColor: sh.tab_color ? { argb: "FF" + sh.tab_color } : undefined }, views: [{ showGridLines: false }] });
    for (const row of sh.rows) for (const c of row.cells) {
      const cell = ws.getCell(row.r, c.c);
      if (c.f) cell.value = { formula: c.f.slice(1), result: c.v as any } as any;
      else if (c.hl) cell.value = { text: String(c.v), hyperlink: c.hl } as any;
      else cell.value = c.v as any;
      cell.numFmt = FORMATS[c.fmt] ?? "General";
      const isText = typeof c.v === "string" && !c.f;
      const font: any = { name: "Arial", size: 10, bold: !!c.b };
      switch (c.s) {
        case "input": font.color = { argb: "FF0000FF" }; cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFFFFFCC" } }; break;
        case "link": font.color = { argb: "FF008000" }; break;
        case "total": font.bold = true; if (!isText) cell.border = { top: { style: "thin", color: { argb: "FF7F7F7F" } } }; break;
        case "header": font.color = { argb: "FFFFFFFF" }; font.bold = true; cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: NAVY } }; cell.alignment = { horizontal: c.c > 1 ? "center" : "left" }; break;
        case "section": font.color = { argb: NAVY }; font.bold = true; font.size = 11; cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFD9E1F2" } }; break;
        case "title": font.color = { argb: NAVY }; font.bold = true; font.size = 16; break;
        case "subtitle": font.color = { argb: "FF595959" }; font.italic = true; break;
        case "note": font.color = { argb: "FF595959" }; font.italic = true; font.size = 9; break;
        case "memo": font.color = { argb: "FF595959" }; font.italic = true; break;
        case "check": font.color = { argb: "FFC00000" }; font.bold = true; cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFE2EFDA" } }; break;
      }
      if (c.hl) { font.color = { argb: "FF0563C1" }; font.underline = true; }
      cell.font = font;
      if (c.i && c.c === 1) cell.alignment = { indent: c.i, wrapText: !!c.w };
      else if (c.w) cell.alignment = { wrapText: true, vertical: "top" };
    }
    for (const [col, w] of Object.entries(sh.col_widths)) ws.getColumn(Number(col)).width = w;
    for (let c = 2; c <= sh.max_col; c++) if (!sh.col_widths[String(c)]) ws.getColumn(c).width = 13;
    if (!Object.keys(sh.col_widths).length) ws.getColumn(1).width = 44;
    for (const m of sh.merges ?? []) ws.mergeCells(m);
    for (const [r, h] of Object.entries(sh.row_heights ?? {})) ws.getRow(Number(r)).height = h;
    if (sh.freeze) { const m = /^([A-Z]+)(\d+)$/.exec(sh.freeze); if (m) { let x = 0; for (const ch of m[1]) x = x * 26 + (ch.charCodeAt(0) - 64); ws.views = [{ state: "frozen", xSplit: x - 1, ySplit: Number(m[2]) - 1, showGridLines: false }]; } }
    ws.pageSetup = { orientation: "landscape", fitToPage: true, fitToWidth: 1, fitToHeight: 0 };
  }
  for (const [name, [sheet, key]] of Object.entries(named)) {
    const sh = (model.sheets as Sheet[]).find((s) => s.name === sheet);
    const hit = sh?.rows.flatMap((r) => r.cells.filter((c) => c.k === key).map((c) => ({ r: r.r, c: c.c })))[0];
    if (hit) wb.definedNames.add(`'${sheet}'!$${colLetter(hit.c)}$${hit.r}`, name);
  }
  const buf = await wb.xlsx.writeBuffer();
  return new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}

export function itemsToOverrides(items: AssumptionItem[], draft: Record<string, number | number[]>): Record<string, unknown> { void items; return draft; }
