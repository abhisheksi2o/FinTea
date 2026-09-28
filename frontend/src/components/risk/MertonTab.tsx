import type { ChartSpec, RiskResponse } from "../../types";
import { Kv, Pill, Section, Stat } from "./Bits";
import { ChartCard } from "./ChartCard";
import { fmtRisk, inputValue, pdTone, stressRows } from "./riskUtils";

export function MertonTab({ r, charts }: { r: RiskResponse; charts: ChartSpec[] }) {
  const s = r.summary;
  const m = r.merton;
  const items = r.inputs.items;
  const rf = inputValue(items, "risk_free");
  const horizon = inputValue(items, "horizon");
  const basis = (key: string) => items.find((i) => i.key === key)?.basis;
  const stress = stressRows(s);
  const mertonCharts = ["merton_structure", "pd_models"].map((id) => charts.find((c) => c.id === id)).filter((c): c is ChartSpec => !!c);
  const narrative = r.feedback.qualitative.find((q) => q.title.startsWith("Market-implied"));

  return (
    <div className="panel">
      <div className="tiles four">
        <Stat label="Naive PD" tag={`${fmtRisk(horizon, "num1")}y`} value={fmtRisk(s.pd_merton_naive, "pct2")} sub={`distance to default ${fmtRisk(s.dd_naive, "score")} sd`} tone={pdTone(s.pd_merton_naive)} />
        <Stat label="Naive PD, risk-free drift" value={fmtRisk(s.pd_naive_rf, "pct2")} sub={`distance to default ${fmtRisk(s.dd_naive_rf, "score")} sd`} tone={pdTone(s.pd_naive_rf)} />
        <Stat label="Iterated PD, risk-neutral" value={fmtRisk(s.pd_merton_rn, "pct2")} sub={`d2 = ${fmtRisk(m?.d2 ?? s.dd_rn, "score")}`} tone={pdTone(s.pd_merton_rn)} />
        <Stat label="Iterated PD, physical drift" value={fmtRisk(s.pd_merton_phys, "pct2")} sub={`expected asset return ${fmtRisk(s.mu, "pct")}`} tone={pdTone(s.pd_merton_phys)} />
      </div>
      <div className="two-col">
        <Section title="Inputs" aside={<span className="muted">editable on the Inputs tab</span>}>
          <Kv rows={[
            { k: "Market equity E", v: `${s.currency} ${fmtRisk(s.market_cap, "num")}m`, note: `${fmtRisk(inputValue(items, "shares_outstanding"), "num1")}m shares × ${s.currency} ${fmtRisk(s.price, "price")} (${s.price_date})` },
            { k: "Equity volatility σE", v: fmtRisk(s.equity_vol, "pct"), note: basis("equity_vol_method") },
            { k: "Expected asset return μ", v: fmtRisk(s.mu, "pct"), note: basis("mu_method") },
            { k: "Risk-free rate r", v: fmtRisk(rf, "pct2"), note: basis("risk_free") },
            { k: "Horizon T", v: `${fmtRisk(horizon, "num2")} year${horizon === 1 ? "" : "s"}`, note: basis("horizon") },
            { k: "Default point F", v: `${s.currency} ${fmtRisk(s.default_point, "num")}m`, note: basis("default_point_method") },
          ]} />
        </Section>
        <Section title="Solution" aside={m ? <Pill tone={m.converged ? "good" : "bad"}>{m.converged ? `converged in ${m.iterations ?? "?"} iterations` : "did not converge"}</Pill> : undefined}>
          <Kv rows={[
            { k: "Naive distance to default", v: `${fmtRisk(s.dd_naive, "score")} sd`, note: "Bharath & Shumway (2008): σV = E/(E+F)·σE + F/(E+F)·(0.05 + 0.25·σE); drift = prior-year equity return" },
            { k: "Asset value V (iterated)", v: `${s.currency} ${fmtRisk(s.asset_value ?? m?.asset_value, "num")}m` },
            { k: "Asset volatility σV (iterated)", v: fmtRisk(s.asset_vol ?? m?.asset_vol, "pct") },
            { k: "d1 / d2", v: `${fmtRisk(m?.d1, "score3")} / ${fmtRisk(m?.d2, "score3")}` },
            { k: "Re-derived equity value / volatility", v: `${s.currency} ${fmtRisk(m?.equity_model, "num")}m / ${fmtRisk(m?.equity_vol_model, "pct")}`, note: m ? `residuals ${fmtRisk(m.residual_equity, "score3")} / ${fmtRisk(m.residual_vol, "score3")}` : undefined },
            { k: "Recovery assumption / expected loss", v: `${fmtRisk(inputValue(items, "recovery_rate"), "pct")} / ${fmtRisk(s.expected_loss, "pct2")}`, note: "expected loss = naive PD × (1 - recovery)" },
            ...(m?.message ? [{ k: "Solver message", v: m.message }] : []),
          ]} />
        </Section>
      </div>
      <div className="two-col">
        <Section title="Stress test" aside={<span className="muted">shock sizes are inputs</span>}>
          <table className="stress">
            <thead><tr><th>Scenario</th><th className="num">Shock</th><th className="num">Base</th><th className="num">Stressed</th></tr></thead>
            <tbody>{stress.map((row) => <tr key={row.scenario}><th scope="row">{row.scenario}</th><td className="num">{row.shock}</td><td className="num muted">{row.base}</td><td className={`num tone-${row.tone}`}>{row.result}</td></tr>)}</tbody>
          </table>
        </Section>
        <Section title="Reading the market-implied risk">
          {narrative ? <ul className="qual-list">{narrative.points.map((p, i) => <li key={i}>{p}</li>)}</ul> : <p className="muted">No narrative available.</p>}
        </Section>
      </div>
      <Section title="Charts">
        <div className="chart-grid">{mertonCharts.map((c) => <ChartCard key={c.id} spec={c} />)}</div>
      </Section>
    </div>
  );
}
