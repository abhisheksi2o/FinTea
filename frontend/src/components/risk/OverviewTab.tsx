import type { ChartSpec, RiskResponse } from "../../types";
import { Kv, Pill, Section, Stat } from "./Bits";
import { ChartCard } from "./ChartCard";
import { Gauge, GradeScale } from "./Gauge";
import { Sparkline } from "./Sparkline";
import { fmtRisk, gradeTone, isNum, pdTone, ratingTone, seriesOf, stressRows, subScoreSpec, voteRows, zoneTone } from "./riskUtils";

const KEY_CHARTS = ["z2_trend", "pd_models", "acct_pd", "leverage"];

export function OverviewTab({ r, charts }: { r: RiskResponse; charts: ChartSpec[] }) {
  const s = r.summary;
  const fb = r.feedback;
  const votes = voteRows(s, fb.distress_votes ?? []);
  const nDistress = isNum(s.agreement) ? s.agreement : votes.filter((v) => v.state === "distress").length;
  const nModels = isNum(s.agreement_n) ? s.agreement_n : votes.filter((v) => v.state !== "na").length;
  const labels = s.series?.labels ?? s.labels ?? [];
  const drivers = [
    { key: "tl_ta", label: "Leverage", measure: "total liabilities / total assets", fmt: "pct", latest: s.tl_ta, tone: s.tl_ta == null ? "muted" : s.tl_ta > 0.8 ? "bad" : s.tl_ta > 0.6 ? "warn" : "good" },
    { key: "int_cov", label: "Coverage", measure: "EBIT / interest expense", fmt: "mult", latest: s.interest_coverage, tone: s.interest_coverage == null ? "muted" : s.interest_coverage < 1.5 ? "bad" : s.interest_coverage < 3 ? "warn" : "good" },
    { key: "current", label: "Liquidity", measure: "current ratio", fmt: "mult", latest: s.current_ratio, tone: s.current_ratio == null ? "muted" : s.current_ratio < 1 ? "bad" : s.current_ratio < 1.5 ? "warn" : "good" },
  ] as const;
  const stress = stressRows(s);
  const narrative = fb.qualitative.filter((q) => q.title !== "Data quality");
  const keyCharts = KEY_CHARTS.map((id) => charts.find((c) => c.id === id)).filter((c): c is ChartSpec => !!c);
  const agreementTone = nModels === 0 ? "muted" : nDistress / nModels >= 0.5 ? "bad" : nDistress > 0 ? "warn" : "good";

  return (
    <div className="panel risk-overview">
      {/* (b) + (c): headline probabilities first */}
      <div className="headline-grid">
        <Stat className="headline" label="Market-implied probability of default" tag="1 year · Merton naive DD" value={fmtRisk(s.pd_merton_naive, "pct2")} tone={pdTone(s.pd_merton_naive)}
          sub={<>Distance to default <b>{fmtRisk(s.dd_naive, "score")} sd</b> (Bharath-Shumway naive, {s.vol_source} volatility {fmtRisk(s.equity_vol, "pct")})</>}>
          <Kv rows={[
            { k: "With risk-free drift", v: fmtRisk(s.pd_naive_rf, "pct2"), note: s.dd_naive_rf != null ? `DD ${fmtRisk(s.dd_naive_rf, "score")} sd` : undefined },
            { k: "Iterated Merton, risk-neutral", v: fmtRisk(s.pd_merton_rn, "pct2") },
            { k: "Iterated Merton, physical drift", v: fmtRisk(s.pd_merton_phys, "pct2") },
            ...(s.pd_cds != null ? [{ k: "Market-quoted (CDS / bond spread)", v: fmtRisk(s.pd_cds, "pct2") }] : []),
            { k: "Expected loss (naive PD × LGD)", v: fmtRisk(s.expected_loss, "pct2") },
          ]} />
        </Stat>
        <Stat className="headline" label="Rating-implied default rate" tag={`synthetic rating ${s.synthetic_rating ?? "n/a"}`} value={<>{fmtRisk(s.pd_rating_1y, "pct2")}<span className="stat-unit"> 1y</span></>} tone={pdTone(s.pd_rating_1y)}
          sub={<>{fmtRisk(s.pd_rating_5y, "pct2")} cumulative over 5 years · historical default rates of the <b>{s.synthetic_rating ?? "n/a"}</b> class</>}>
          <Kv rows={[
            { k: "Rating basis", v: s.rating_source ?? "n/a" },
            { k: "Interest coverage", v: s.interest_coverage == null ? "not reported" : `${fmtRisk(s.interest_coverage, "mult")} EBIT / interest` },
            { k: "Default spread", v: fmtRisk(s.default_spread, "pct2"), note: s.implied_cost_of_debt != null ? `implied pre-tax cost of debt ${fmtRisk(s.implied_cost_of_debt, "pct2")}` : undefined },
            { k: "EM-score rating cross-check", v: <Pill tone={ratingTone(s.em_rating)}>{s.em_rating ?? "n/a"}</Pill> },
          ]} />
        </Stat>
        <Stat className="headline" label="Altman Z''" tag={`1995 model · ${s.base_label ?? "latest fiscal year"}`} value={fmtRisk(s.altman_z2, "score")} tone={zoneTone(s.altman_z2_zone)}
          sub={<><Pill tone={zoneTone(s.altman_z2_zone)}>{s.altman_z2_zone ? `${s.altman_z2_zone} zone` : "n/a"}</Pill> &nbsp;bond-rating equivalent <Pill tone={ratingTone(s.em_rating)}>{s.em_rating ?? "n/a"}</Pill></>}>
          <Kv rows={[
            { k: "Altman Z (market equity)", v: `${fmtRisk(s.altman_z, "score")} · ${s.altman_zone ?? "n/a"}` },
            { k: "Altman Z' (book equity)", v: `${fmtRisk(s.altman_z1, "score")} · ${s.altman_z1_zone ?? "n/a"}` },
            { k: "EM score (Z'' + 3.25)", v: fmtRisk(s.em_score, "score") },
            { k: "Zones", v: "safe > 2.60 · grey 1.10-2.60 · distress < 1.10" },
          ]} />
        </Stat>
      </div>

      {/* (d) model agreement + (e) drivers */}
      <div className="two-col">
        <Section title="Model agreement" aside={<Pill tone={agreementTone}>{nDistress} of {nModels} signal distress</Pill>}>
          <p className="lead"><b>{nDistress} of {nModels}</b> applicable distress models classify {s.company} as distressed.</p>
          <ul className="votes">
            {votes.map((v) => (
              <li key={v.model} className={`vote ${v.state}`}>
                <span className="vote-dot" aria-hidden="true" />
                <span className="vote-model">{v.model}</span>
                <span className="vote-detail">{v.detail}</span>
                <Pill tone={v.state === "distress" ? "bad" : v.state === "clear" ? "good" : "muted"}>{v.state === "distress" ? "Distress" : v.state === "clear" ? "No distress" : "n/a"}</Pill>
              </li>
            ))}
          </ul>
          {fb.qualitative.find((q) => q.title === "Model agreement")?.points.slice(1).map((p, i) => <p key={i} className="muted">{p}</p>)}
        </Section>
        <Section title="Drivers" aside={<span className="muted">{s.n_annual ?? labels.length} fiscal year{(s.n_annual ?? labels.length) === 1 ? "" : "s"}{s.ltm ? " + latest twelve months" : ""}: {labels[0]}{labels.length > 1 ? ` - ${labels[labels.length - 1]}` : ""}</span>}>
          <table className="drivers">
            <thead><tr><th>Driver</th><th>Trend</th><th className="num">Latest</th><th>Measure</th></tr></thead>
            <tbody>
              {drivers.map((d) => {
                const vals = seriesOf(s, d.key);
                return (
                  <tr key={d.key}>
                    <th scope="row">{d.label}</th>
                    <td className="spark-cell">{vals.some(isNum) ? <Sparkline values={vals} width={110} height={28} /> : <span className="muted">n/a</span>}</td>
                    <td className={`num tone-${d.tone}`}>{d.key === "int_cov" && d.latest == null ? "not reported" : fmtRisk(d.latest, d.fmt)}</td>
                    <td className="muted">{d.measure}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Kv rows={[
            { k: "Net debt / EBITDA", v: fmtRisk(s.nd_ebitda, "mult") },
            { k: "Cash from operations / total debt", v: fmtRisk(s.cfo_debt, "pct") },
            { k: "Liquidity coverage, 12 months", v: fmtRisk(s.liquidity_coverage_12m, "mult"), note: "cash and short-term investments over the next 12 months of debt service and cash burn" },
            { k: "Cash runway", v: s.runway_years == null ? "not burning cash" : `${fmtRisk(s.runway_years, "num1")} years` },
          ]} />
        </Section>
      </div>

      {/* secondary: distress signal index + stress test */}
      <div className="two-col">
        <Section title="Distress signal index" aside={<span className="index-caveat">uncalibrated index, not a probability of default</span>} className="index-card">
          <div className="index-body">
            <Gauge score={s.composite_score} grade={s.composite_grade} width={170} />
            <div>
              <div className="index-grade"><Pill tone={gradeTone(s.composite_grade)}>{s.composite_grade} band</Pill> <span className="muted">{fmtRisk(s.composite_score, "num1")} / 100 weighted · {fmtRisk(s.composite_equal, "num1")} equal-weight</span></div>
              <p className="muted">A weighted average of seven signals rescaled to 0-100 (weights on the Inputs tab). It ranks companies and summarises agreement between models; it is not calibrated to observed default frequencies. Read the probabilities above for the level of risk.</p>
              <GradeScale score={s.composite_score} grade={s.composite_grade} />
            </div>
          </div>
        </Section>
        <Section title="Stress test" aside={<span className="muted">one-year Merton PD and Altman Z'' under simple shocks</span>}>
          {stress.length ? (
            <table className="stress">
              <thead><tr><th>Scenario</th><th className="num">Shock</th><th className="num">Base</th><th className="num">Stressed</th></tr></thead>
              <tbody>
                {stress.map((row) => <tr key={row.scenario}><th scope="row">{row.scenario}</th><td className="num">{row.shock}</td><td className="num muted">{row.base}</td><td className={`num tone-${row.tone}`}>{row.result}</td></tr>)}
              </tbody>
            </table>
          ) : <p className="muted">No stress scenarios in this analysis.</p>}
          <p className="muted small">Shock sizes are inputs (Stress test section). Equity and volatility shocks feed the naive distance to default; the EBIT shock is applied to the Z'' EBIT term.</p>
        </Section>
      </div>

      <div className="tiles">
        <Stat label="Ohlson O probability" value={fmtRisk(s.ohlson_pd, "pct")} sub={s.ohlson_flag ?? (s.has_prior_year ? "n/a" : "needs a prior fiscal year")} tone={pdTone(s.ohlson_pd)} />
        <Stat label="Zmijewski probability" value={fmtRisk(s.zmijewski_pd, "pct")} sub={s.zmijewski_flag ?? "n/a"} tone={pdTone(s.zmijewski_pd)} />
        <Stat label="Piotroski F-score" value={s.piotroski == null ? "n/a" : `${fmtRisk(s.piotroski, "int")} / 9`} sub={s.piotroski_class ?? (s.has_prior_year ? "n/a" : "needs a prior fiscal year")} />
        <Stat label="Beneish M-score" tag="earnings quality" value={fmtRisk(s.beneish_m, "score")} sub={s.beneish_flag ?? (s.has_prior_year ? "n/a" : "needs a prior fiscal year")} tone={s.beneish_flag ? (s.beneish_flag.toLowerCase().includes("manipulation") ? "bad" : undefined) : undefined} />
        <Stat label="Interest coverage" value={s.interest_coverage == null ? "not reported" : fmtRisk(s.interest_coverage, "mult")} sub={s.interest_coverage == null && s.interest_estimated_coverage != null ? `estimated ${fmtRisk(s.interest_estimated_coverage, "mult")} on imputed interest` : "EBIT / interest expense"} />
        <Stat label="Net debt / EBITDA" value={fmtRisk(s.nd_ebitda, "mult")} sub={s.nd_ebitda != null && s.nd_ebitda < 0 ? "net cash or negative EBITDA" : (s.base_label ?? "latest fiscal year")} />
        <Stat label="Equity volatility" value={fmtRisk(s.equity_vol, "pct")} sub={`${fmtRisk(s.n_returns, "int")} ${s.vol_source} returns, annualised`} />
        <Stat label="Market capitalisation" value={`${s.currency} ${fmtRisk(s.market_cap, "num")}m`} sub={s.market_cap_usd_bn != null ? `USD ${fmtRisk(s.market_cap_usd_bn, "num1")}bn · price ${fmtRisk(s.price, "price")} on ${s.price_date}` : undefined} />
      </div>

      <div className="two-col narrative-grid">
        <Section title="Assessment">
          {narrative.map((q) => (
            <div className="qual" key={q.title}>
              <h4>{q.title === "Earnings quality" ? "Earnings quality (Piotroski, Beneish)" : q.title}</h4>
              <ul>{q.points.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          ))}
        </Section>
        <div>
          <Section title="Key charts">
            <div className="chart-stack">
              {keyCharts.map((c) => <ChartCard key={c.id} spec={c} height={230} />)}
              <ChartCard spec={subScoreSpec(s)} height={250} />
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
