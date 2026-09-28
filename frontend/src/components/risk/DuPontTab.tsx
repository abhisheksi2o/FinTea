import type { ChartSpec, RiskResponse } from "../../types";
import { Section, Stat } from "./Bits";
import { ChartCard } from "./ChartCard";
import { Sparkline } from "./Sparkline";
import { fmtRisk, isNum, seriesOf } from "./riskUtils";

interface Term { key: string; label: string; fmt: string; sub?: string }

const THREE: Term[] = [
  { key: "net_margin", label: "Net margin", fmt: "pct", sub: "net income / revenue" },
  { key: "asset_turnover", label: "Asset turnover", fmt: "mult", sub: "revenue / total assets" },
  { key: "equity_multiplier", label: "Equity multiplier", fmt: "mult", sub: "total assets / book equity" },
];
const FIVE: Term[] = [
  { key: "tax_burden", label: "Tax burden", fmt: "pct", sub: "net income / pre-tax income" },
  { key: "interest_burden", label: "Interest burden", fmt: "pct", sub: "pre-tax income / EBIT" },
  { key: "ebit_margin", label: "EBIT margin", fmt: "pct", sub: "EBIT / revenue" },
  { key: "asset_turnover", label: "Asset turnover", fmt: "mult", sub: "revenue / total assets" },
  { key: "equity_multiplier", label: "Equity multiplier", fmt: "mult", sub: "total assets / book equity" },
];
const ROWS: Term[] = [
  { key: "roe", label: "Return on equity", fmt: "pct" },
  { key: "roa_dupont", label: "Return on assets", fmt: "pct" },
  { key: "net_margin", label: "Net margin", fmt: "pct" },
  { key: "asset_turnover", label: "Asset turnover (x)", fmt: "mult" },
  { key: "equity_multiplier", label: "Equity multiplier (x)", fmt: "mult" },
  { key: "tax_burden", label: "Tax burden", fmt: "pct" },
  { key: "interest_burden", label: "Interest burden", fmt: "pct" },
  { key: "ebit_margin", label: "EBIT margin", fmt: "pct" },
];

function Equation({ result, resultLabel, terms, values }: { result: number | null | undefined; resultLabel: string; terms: Term[]; values: Record<string, number | null | undefined> }) {
  return (
    <div className="dupont-eq" role="group" aria-label={resultLabel}>
      <div className="dupont-box result">
        <div className="dupont-box-label">{resultLabel}</div>
        <div className="dupont-box-value">{fmtRisk(result, "pct")}</div>
      </div>
      <span className="dupont-op">=</span>
      {terms.map((t, i) => (
        <span key={t.key} className="dupont-term">
          {i > 0 && <span className="dupont-op">&times;</span>}
          <div className="dupont-box">
            <div className="dupont-box-label">{t.label}</div>
            <div className="dupont-box-value">{fmtRisk(values[t.key], t.fmt)}</div>
            {t.sub && <div className="dupont-box-sub">{t.sub}</div>}
          </div>
        </span>
      ))}
    </div>
  );
}

export function DuPontTab({ r, charts }: { r: RiskResponse; charts: ChartSpec[] }) {
  const s = r.summary;
  const d = (s.dupont ?? {}) as Record<string, number | null | undefined>;
  const labels = s.series?.labels ?? s.labels ?? [];
  const latest = s.base_label ?? labels[labels.length - 1] ?? "latest fiscal year";
  const negEquity = d.roe == null && isNum(d.net_margin);
  const dupontCharts = ["dupont_roe", "dupont_margins", "dupont_leverage"].map((id) => charts.find((c) => c.id === id)).filter((c): c is ChartSpec => !!c);
  const narrative = r.feedback.qualitative.find((q) => q.title.startsWith("Profitability"))?.points.filter((p) => p.startsWith("DuPont")) ?? [];

  return (
    <div className="panel">
      {negEquity && (
        <div className="caveat">
          <b>Book equity is not positive in {latest}.</b> Return on equity and the equity multiplier are undefined; the margin and turnover drivers below still describe the operating performance, and the leverage story is in the Ratios tab.
        </div>
      )}
      <Section title={`Three-step DuPont (${latest})`} aside={<span className="muted">ROE = net margin &times; asset turnover &times; equity multiplier, on ending balances</span>}>
        <Equation result={d.roe} resultLabel="Return on equity" terms={THREE} values={d} />
      </Section>
      <Section title={`Five-step DuPont (${latest})`} aside={<span className="muted">splits the net margin into tax burden, interest burden and EBIT margin</span>}>
        <Equation result={d.roe_five_step ?? d.roe} resultLabel="Return on equity" terms={FIVE} values={d} />
      </Section>
      <div className="tiles four">
        <Stat label="Return on assets" value={fmtRisk(d.roa, "pct")} sub="net margin × asset turnover" />
        <Stat label="Leverage contribution" value={fmtRisk(d.leverage_effect, "pct")} sub="ROE - ROA, percentage points" tone={isNum(d.leverage_effect) && d.equity_multiplier != null && d.equity_multiplier > 5 ? "warn" : undefined} />
        <Stat label="Change in ROE" value={fmtRisk(d.roe_change, "pct")} sub={labels.length > 1 ? `${latest} vs ${labels[labels.length - 2]}` : "needs a prior period"} />
        <Stat label="Equity multiplier" value={fmtRisk(d.equity_multiplier, "mult")} sub={isNum(d.equity_multiplier) && d.equity_multiplier > 5 ? "above 5x: most of the ROE comes from leverage" : "total assets / book equity"} tone={isNum(d.equity_multiplier) && d.equity_multiplier > 5 ? "warn" : undefined} />
      </div>
      <Section title={s.ltm ? "Drivers by fiscal year and latest twelve months" : "Drivers by fiscal year"} aside={<span className="muted">blank where book equity was not positive</span>}>
        <div className="table-scroll">
          <table className="ratios">
            <thead><tr><th>Driver</th><th>Trend</th>{labels.map((l) => <th key={l} className="num">{l}</th>)}</tr></thead>
            <tbody>
              {ROWS.map((row) => {
                const vals = seriesOf(s, row.key);
                return (
                  <tr key={row.key}>
                    <th scope="row">{row.label}</th>
                    <td className="spark-cell">{vals.some(isNum) ? <Sparkline values={vals} width={100} height={26} /> : <span className="muted">n/a</span>}</td>
                    {labels.map((l, i) => <td key={l} className={`num${i === labels.length - 1 ? " last" : ""}${!isNum(vals[i]) ? " na" : ""}`}>{fmtRisk(vals[i], row.fmt)}</td>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
      {narrative.length > 0 && (
        <Section title="Reading the decomposition">
          <ul className="qual-list">{narrative.map((p, i) => <li key={i}>{p}</li>)}</ul>
          <p className="muted small">How to read it: a high ROE built on a high equity multiplier is leverage, not operating strength; a rising ROE with a falling net margin means the balance sheet, not the business, is doing the work.</p>
        </Section>
      )}
      <Section title="Charts" aside={<span className="muted">also on the DuPont sheet of the Excel report</span>}>
        <div className="chart-grid">{dupontCharts.map((c) => <ChartCard key={c.id} spec={c} />)}</div>
      </Section>
    </div>
  );
}
