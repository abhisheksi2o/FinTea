import type { ChartSpec, RiskResponse } from "../../types";
import { Section, Stat } from "./Bits";
import { ChartCard } from "./ChartCard";
import { Sparkline } from "./Sparkline";
import { fmtRisk, isNum, seriesOf } from "./riskUtils";

interface RatioDef { key: string; label: string; fmt: string; group: string; note?: string }

export function RatiosTab({ r, charts }: { r: RiskResponse; charts: ChartSpec[] }) {
  const s = r.summary;
  const labels = s.series?.labels ?? s.labels ?? [];
  const defs: RatioDef[] = [
    { key: "tl_ta", label: "Total liabilities / total assets", fmt: "pct", group: "Leverage" },
    { key: "equity_ta", label: "Book equity / total assets", fmt: "pct", group: "Leverage" },
    { key: "de", label: "Total debt / book equity", fmt: "mult", group: "Leverage", note: "undefined when equity is negative" },
    { key: "nd_ebitda", label: "Net debt / EBITDA", fmt: "mult", group: "Leverage" },
    { key: "int_cov", label: "Interest coverage (EBIT / interest)", fmt: "mult", group: "Coverage", note: "n/a when interest expense is not reported" },
    { key: "cfo_debt", label: "Cash from operations / total debt", fmt: "pct", group: "Coverage" },
    { key: "current", label: "Current ratio", fmt: "mult", group: "Liquidity" },
    { key: "quick", label: "Quick ratio", fmt: "mult", group: "Liquidity" },
    { key: "roa", label: "Return on assets", fmt: "pct", group: "Profitability" },
    { key: "revenue", label: `Revenue (${s.units})`, fmt: "num", group: "Scale" },
    { key: "net_income", label: `Net income (${s.units})`, fmt: "num", group: "Scale" },
    { key: "fcf", label: `Free cash flow (${s.units})`, fmt: "num", group: "Scale" },
    { key: "total_debt", label: `Total debt (${s.units})`, fmt: "num", group: "Scale" },
    { key: "cash", label: `Cash and short-term investments (${s.units})`, fmt: "num", group: "Scale" },
    { key: "total_equity", label: `Book equity (${s.units})`, fmt: "num", group: "Scale" },
  ];
  const groups = Array.from(new Set(defs.map((d) => d.group)));
  const ratioCharts = ["leverage", "liquidity"].map((id) => charts.find((c) => c.id === id)).filter((c): c is ChartSpec => !!c);

  return (
    <div className="panel">
      <div className="tiles four">
        <Stat label="Liquidity coverage, 12 months" value={fmtRisk(s.liquidity_coverage_12m, "mult")} sub="cash and short-term investments / (debt due within a year + cash burn)" />
        <Stat label="Cash runway" value={s.runway_years == null ? "n/a" : `${fmtRisk(s.runway_years, "num1")} yrs`} sub={s.runway_years == null ? "free cash flow is positive - no cash burn" : "cash balance / negative free cash flow"} />
        <Stat label="Debt / equity" value={fmtRisk(s.debt_to_equity, "mult")} sub={s.debt_to_equity != null && s.debt_to_equity < 0 ? "negative book equity" : "total debt / book equity"} />
        <Stat label="Quick ratio" value={fmtRisk(s.quick_ratio, "mult")} sub={`current ratio ${fmtRisk(s.current_ratio, "mult")}`} />
      </div>
      <Section title="Ratio trends" aside={<span className="muted">{s.n_annual ?? labels.length} fiscal year{(s.n_annual ?? labels.length) === 1 ? "" : "s"}{s.ltm ? " plus the latest twelve months" : ""} from the reported statements · negative values shown with a minus</span>}>
        <div className="table-scroll">
          <table className="ratios">
            <thead>
              <tr><th>Ratio</th><th>Trend</th>{labels.map((l) => <th key={l} className="num">{l}</th>)}</tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <GroupRows key={g} group={g} defs={defs.filter((d) => d.group === g)} labels={labels} s={s} />
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Charts">
        <div className="chart-grid">{ratioCharts.map((c) => <ChartCard key={c.id} spec={c} />)}</div>
      </Section>
    </div>
  );
}

function GroupRows({ group, defs, labels, s }: { group: string; defs: RatioDef[]; labels: string[]; s: RiskResponse["summary"] }) {
  return (
    <>
      <tr className="group-row"><th colSpan={labels.length + 2}>{group}</th></tr>
      {defs.map((d) => {
        const vals = seriesOf(s, d.key);
        return (
          <tr key={d.key}>
            <th scope="row">{d.label}{d.note && <div className="kv-note">{d.note}</div>}</th>
            <td className="spark-cell">{vals.some(isNum) ? <Sparkline values={vals} width={100} height={26} /> : <span className="muted">n/a</span>}</td>
            {labels.map((l, i) => <td key={l} className={`num${i === labels.length - 1 ? " last" : ""}${!isNum(vals[i]) ? " na" : ""}`}>{fmtRisk(vals[i], d.fmt)}</td>)}
          </tr>
        );
      })}
    </>
  );
}
