import { useMemo, useState } from "react";
import type { ChartSpec, RiskBasis, RiskResponse } from "../../types";
import { SheetGrid } from "../SheetGrid";
import { Pill } from "./Bits";
import { ChartCard } from "./ChartCard";
import { DataQualityTab } from "./DataQualityTab";
import { DuPontTab } from "./DuPontTab";
import { MertonTab } from "./MertonTab";
import { ModelsTab } from "./ModelsTab";
import { OverviewTab } from "./OverviewTab";
import { RatiosTab } from "./RatiosTab";
import { RiskInputsPanel } from "./RiskInputsPanel";
import { fmtDate, fmtRisk, subScoreSpec, tidyChart } from "./riskUtils";

interface Props {
  r: RiskResponse; busy: boolean; staticMode: boolean; staticNotice: string; onRebuild: (overrides: Record<string, unknown>) => void;
  /** Re-run the analysis on the other statement basis (live app only). */
  onBasis?: (b: RiskBasis) => void;
  /** Browser-side Excel export for pre-built (static) reports. */
  onExport?: () => void; exporting?: boolean;
}

export const RISK_PANELS = ["Overview", "Charts", "Models", "Ratios", "DuPont", "Merton", "Inputs", "Data quality"] as const;

export function RiskView({ r, busy, staticMode, staticNotice, onRebuild, onBasis, onExport, exporting }: Props) {
  const s = r.summary;
  const baseLabel = s.base_label ?? s.labels?.[s.labels.length - 1] ?? "n/a";
  const ltmWanted = (s.basis ?? "ltm") === "ltm";
  const canSwitch = !staticMode && !!onBasis && (s.ltm || s.basis === "annual");
  const [tab, setTab] = useState<string>("Overview");
  const charts: ChartSpec[] = useMemo(() => (r.charts ?? r.sheets?.flatMap((sh) => sh.charts ?? []) ?? []).map((c) => tidyChart(c, s)), [r.charts, r.sheets, s]);
  const sheets = r.sheets ?? [];
  const sheet = tab.startsWith("sheet:") ? sheets.find((sh) => `sheet:${sh.name}` === tab) : undefined;
  const dqTone = s.n_fail > 0 ? "bad" : s.n_flag > 0 ? "warn" : "good";
  const ver = r.verification;
  const verTone = ver.status === "verified" ? "good" : ver.status === "mismatch" ? "bad" : "warn";
  const verText = ver.status === "verified" ? `${ver.cells_checked.toLocaleString()} formulas verified by ${ver.engine ?? "LibreOffice"}` : ver.status === "mismatch" ? `${ver.n_mismatches ?? ver.mismatches.length} formula mismatch(es)` : `formula verification ${ver.status}`;
  const meta = [
    [s.sector, s.industry].filter(Boolean).join(" / "),
    s.price != null ? `${s.currency} ${fmtRisk(s.price, "price")} on ${s.price_date}` : null,
    s.market_cap_usd_bn != null ? `market cap USD ${fmtRisk(s.market_cap_usd_bn, "num1")}bn` : null,
    s.units,
  ].filter(Boolean) as string[];

  return (
    <div className="risk-view">
      <div className="risk-head">
        <div className="risk-title">
          <div className="risk-kicker">Default risk analysis</div>
          <h2>{s.company} <span className="sym">{s.symbol}</span>{s.exchange && <span className="exch">{s.exchange}</span>}</h2>
          <div className="risk-meta">{meta.map((m, i) => <span key={i}>{m}</span>)}</div>
        </div>
        <div className="downloads">
          {r.download_url ? (
            <a className="button primary" href={r.download_url} download>Download Excel report</a>
          ) : (
            <button className="primary" onClick={onExport} disabled={!onExport || exporting} title="Written in your browser from the pre-built report: every formula and data block, without the native chart objects">{exporting ? "Writing workbook..." : "Download Excel report"}</button>
          )}
          {!staticMode && r.download_url && ver.status === "verified" && (
            <a className="button" href={`${r.download_url}?recalculated=1`} download title="Same workbook re-saved with cached values so previews (mail, Drive, phone) show numbers without recalculating">Download with cached values</a>
          )}
        </div>
      </div>
      <div className="status-strip">
        <span className="asof">As of <b>{s.price_date}</b> (price) · statements to <b>{baseLabel}</b>{s.ltm && s.balance_date ? ` (balance sheet ${s.balance_date})` : ""} · {s.source} · retrieved {fmtDate(s.retrieved_at)}{r.meta?.generated ? ` · analysed ${r.meta.generated}` : ""}</span>
        <span className="badges">
          <Pill tone={s.ltm ? "good" : "muted"} title={s.basis_note ?? undefined}>{s.ltm ? "Latest twelve months" : "Fiscal-year basis"}</Pill>
          {canSwitch && (
            <button type="button" className="linkish small" onClick={() => onBasis!(s.ltm ? "annual" : "ltm")} disabled={busy} title={s.ltm ? "Re-run on the last reported fiscal year" : "Re-run on the last four quarters"}>
              {s.ltm ? "use fiscal year" : "use latest 12 months"}
            </button>
          )}
          <Pill tone={dqTone} title={`${fmtRisk(s.n_fail, "int")} failure(s), ${fmtRisk(s.n_flag, "int")} flag(s)`}>Data: {s.dq_status} · {fmtRisk(s.n_fail, "int")} fail / {fmtRisk(s.n_flag, "int")} flag</Pill>
          <Pill tone={verTone}>{verText}</Pill>
        </span>
      </div>
      {s.ltm && s.periods_note && <div className="basis-note muted small">{s.periods_note}. Quarterly statements are unaudited; the year-over-year models compare the LTM column with the last fiscal year.</div>}
      {!s.ltm && ltmWanted && s.basis_note && <div className="basis-note muted small">{s.basis_note}</div>}
      {s.financial_sector && (
        <div className="caveat">
          <b>Financial-sector company.</b> Altman, Ohlson, Zmijewski, Springate, Grover and Taffler were estimated on industrial firms; their ratios (working capital, liabilities / assets, EBIT coverage) are not meaningful for banks and insurers, whose leverage is the business model. Read the accounting scores as not applicable and rely on the market-implied (Merton) view, the rating and regulatory capital measures instead.
        </div>
      )}

      <nav className="tabs risk-tabs" aria-label="Analysis sections">
        {RISK_PANELS.map((t) => (
          <button key={`panel-${t}`} className={t === tab ? "active" : ""} onClick={() => setTab(t)} aria-current={t === tab ? "page" : undefined}>{t}</button>
        ))}
        <span className="tabs-group-label" aria-hidden="true">Excel sheets</span>
        {sheets.map((sh) => (
          <button key={`sheet-${sh.name}`} className={`sheet-tab${`sheet:${sh.name}` === tab ? " active" : ""}`} onClick={() => setTab(`sheet:${sh.name}`)} aria-current={`sheet:${sh.name}` === tab ? "page" : undefined} title={`${sh.name} sheet of the Excel report`}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M1.5 6.5h13M1.5 10h13M6 2.5v11M10.5 2.5v11" stroke="currentColor" strokeWidth="1" /></svg>{sh.name}
          </button>
        ))}
      </nav>

      {tab === "Overview" && <OverviewTab r={r} charts={charts} />}
      {tab === "Charts" && (
        <div className="panel">
          <p className="muted panel-intro">Every chart is also embedded in the Dashboard sheet of the Excel report and reads from the same formula cells. Hover for exact values.</p>
          <div className="chart-grid">
            {charts.map((c) => <ChartCard key={c.id} spec={c} />)}
            <ChartCard spec={subScoreSpec(s)} />
          </div>
        </div>
      )}
      {tab === "Models" && <ModelsTab r={r} charts={charts} />}
      {tab === "Ratios" && <RatiosTab r={r} charts={charts} />}
      {tab === "DuPont" && <DuPontTab r={r} charts={charts} />}
      {tab === "Merton" && <MertonTab r={r} charts={charts} />}
      {tab === "Inputs" && <RiskInputsPanel items={r.inputs.items} busy={busy} onRebuild={onRebuild} staticMode={staticMode} staticNotice={staticNotice} />}
      {tab === "Data quality" && <DataQualityTab r={r} />}
      {sheet && <SheetGrid key={sheet.name} sheet={sheet} />}
    </div>
  );
}
