import type { ChartSpec, RiskResponse } from "../../types";
import { Kv, Pill, Section } from "./Bits";
import { ChartCard } from "./ChartCard";
import { fmtRisk, isNum, modelRows, ratingTone, seriesOf } from "./riskUtils";

const GROUP_NOTE: Record<string, string> = {
  "Altman family": "Discriminant scores; X4 uses market equity for Z and book equity for Z' and Z''. Zones: Z safe > 2.99 / distress < 1.81; Z' safe > 2.90 / distress < 1.23; Z'' safe > 2.60 / distress < 1.10.",
  "Probability models": "Ohlson (logit) and Zmijewski (probit) map accounting ratios to a probability of financial distress; both need a prior year for the change terms (Ohlson).",
  "Other discriminant models": "Springate (Canada), Grover and Taffler (UK) scores with the published coefficients and cut-offs.",
  "Earnings quality": "Piotroski F counts nine strength signals year over year. Beneish M is an earnings-manipulation screen - an earnings-quality signal, not a default model - and does not enter the distress votes.",
};

export function ModelsTab({ r, charts }: { r: RiskResponse; charts: ChartSpec[] }) {
  const s = r.summary;
  const rows = modelRows(s, r.feedback.distress_votes ?? []);
  const labels = s.series?.labels ?? s.labels ?? [];
  const groups = Array.from(new Set(rows.map((x) => x.group)));
  const modelCharts = ["z2_trend", "z_z1_trend", "acct_pd", "piotroski", "beneish"].map((id) => charts.find((c) => c.id === id)).filter((c): c is ChartSpec => !!c);

  return (
    <div className="panel">
      {groups.map((g) => (
        <Section key={g} title={g} aside={<span className="muted">{GROUP_NOTE[g]}</span>}>
          <div className="table-scroll">
            <table className="models">
              <thead>
                <tr><th>Model</th>{labels.map((l) => <th key={l} className="num">{l}</th>)}<th>Verdict</th><th>Distress vote</th></tr>
              </thead>
              <tbody>
                {rows.filter((x) => x.group === g).map((x) => {
                  const vals = x.seriesKey ? seriesOf(s, x.seriesKey) : [];
                  return (
                    <tr key={x.key}>
                      <th scope="row">{x.model}{x.note && <div className="kv-note">{x.note}</div>}</th>
                      {labels.map((l, i) => {
                        const v = x.seriesKey ? vals[i] : i === labels.length - 1 ? x.latest : null;
                        const last = i === labels.length - 1;
                        return <td key={l} className={`num${last ? " last" : ""}${!isNum(v) ? " na" : ""}`}>{fmtRisk(v, x.fmt)}</td>;
                      })}
                      <td>{x.verdict ? <Pill tone={x.tone}>{x.verdict}</Pill> : <span className="muted">-</span>}</td>
                      <td>{x.vote ? (isNum(x.latest) ? <Pill tone={x.vote.distress ? "bad" : "good"}>{x.vote.distress ? "Distress" : "No distress"}</Pill> : <Pill tone="muted">n/a</Pill>) : <span className="muted">not a vote</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      ))}

      <Section title="Synthetic rating" aside={<span className="muted">interest coverage mapped to a bond rating (Damodaran tables), cross-checked with the Altman EM score</span>}>
        <div className="two-col">
          <Kv rows={[
            { k: "Synthetic rating", v: <Pill tone={ratingTone(s.synthetic_rating)}>{s.synthetic_rating ?? "n/a"}</Pill>, note: s.rating_source ?? undefined },
            { k: "Interest coverage (reported interest)", v: s.interest_coverage == null ? "not reported" : fmtRisk(s.interest_coverage, "mult") },
            { k: "Coverage on estimated interest", v: fmtRisk(s.interest_estimated_coverage, "mult"), note: "average total debt × (risk-free + BBB spread); used when interest expense is not reported and the fallback is set to 2" },
            { k: "Rating on 3-year average EBIT", v: <Pill tone={ratingTone(s.rating_on_avg_ebit)}>{s.rating_on_avg_ebit ?? "n/a"}</Pill>, note: "smooths a single bad or good year" },
            { k: "Rating from coverage / from EM score", v: `${s.rating_cov ?? "n/a"} / ${s.rating_em ?? "n/a"}` },
          ]} />
          <Kv rows={[
            { k: "Default spread", v: fmtRisk(s.default_spread, "pct2") },
            { k: "Implied pre-tax cost of debt", v: fmtRisk(s.implied_cost_of_debt, "pct2"), note: "risk-free + default spread" },
            { k: "Historical default rate, 1 year", v: fmtRisk(s.pd_rating_1y, "pct2") },
            { k: "Historical default rate, 5 years (cumulative)", v: fmtRisk(s.pd_rating_5y, "pct2") },
            { k: "Market-quoted PD (CDS / bond spread)", v: s.pd_cds == null ? "no spread entered (Inputs tab)" : fmtRisk(s.pd_cds, "pct2") },
          ]} />
        </div>
      </Section>

      <Section title="Model charts">
        <div className="chart-grid">{modelCharts.map((c) => <ChartCard key={c.id} spec={c} />)}</div>
      </Section>
    </div>
  );
}
