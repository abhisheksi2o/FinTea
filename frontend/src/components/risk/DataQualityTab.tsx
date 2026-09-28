import { fmtValue } from "../../format";
import type { RiskResponse } from "../../types";
import { Pill, Section } from "./Bits";
import { applicabilityTone, fmtRisk } from "./riskUtils";

export function DataQualityTab({ r }: { r: RiskResponse }) {
  const { feedback: fb, verification: v, summary: s } = r;
  const dqTone = fb.n_fail > 0 ? "fail" : fb.n_flag > 0 ? "flag" : "pass";
  const dq = fb.qualitative.find((q) => q.title === "Data quality");
  return (
    <div className="panel">
      <div className={`status-banner ${dqTone}`}>
        <b>{fb.status}</b>
        <span>{fmtRisk(fb.n_fail, "int")} integrity failure(s), {fmtRisk(fb.n_flag, "int")} flag(s) across {fb.quantitative.length} checks</span>
      </div>
      <div className="verify">
        {v.status === "verified" && <span className="ok">Formula verification: {v.cells_checked.toLocaleString()} formula cells recalculated by {v.engine} match FinTea's engine (largest difference {v.max_abs_diff?.toExponential(1)}).</span>}
        {v.status === "mismatch" && <span className="bad">Formula verification found {v.n_mismatches} mismatching cell(s), e.g. {v.mismatches[0]?.sheet}!{v.mismatches[0]?.cell}.</span>}
        {v.status === "skipped" && <span className="warn">Formula verification skipped: {v.reason}</span>}
        {fb.verification_text && v.status !== "verified" && <div className="muted">{fb.verification_text}</div>}
      </div>

      <Section title="Model applicability" aside={<span className="muted">which models the available data supports</span>}>
        <table className="applic">
          <thead><tr><th>Model</th><th>Status</th><th>Missing inputs</th></tr></thead>
          <tbody>
            {(s.applicability ?? []).map((a) => {
              const tone = applicabilityTone(a.status, a.missing ?? []);
              return (
                <tr key={a.model}>
                  <th scope="row">{a.model}</th>
                  <td><Pill tone={tone}>{a.status}</Pill></td>
                  <td className="muted">{a.missing?.length ? a.missing.join(", ") : "-"}</td>
                </tr>
              );
            })}
            {(!s.applicability || s.applicability.length === 0) && <tr><td colSpan={3} className="muted">Not reported by this analysis.</td></tr>}
          </tbody>
        </table>
      </Section>

      <Section title="Quantitative checks" aside={<span className="muted">every check is a live formula on the Data Quality sheet</span>}>
        <div className="table-scroll">
          <table className="checks">
            <thead><tr><th>Check</th><th className="num">Value</th><th>Threshold</th><th>Status</th><th>Why it matters</th></tr></thead>
            <tbody>
              {fb.quantitative.map((q) => (
                <tr key={q.check} className={q.status.toLowerCase()}>
                  <td>{q.check}</td><td className="num">{q.value == null ? "n/a" : fmtValue(q.value, q.fmt) || "0"}</td><td>{q.threshold}</td>
                  <td><Pill tone={q.status === "PASS" ? "good" : q.status === "FLAG" ? "warn" : "bad"}>{q.status}</Pill></td><td className="why">{q.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="two-col">
        <Section title="Data quality notes">
          {dq ? <ul className="qual-list">{dq.points.map((p, i) => <li key={i}>{p}</li>)}</ul> : <p className="muted">No notes.</p>}
          <div className="muted small">Source: {s.source}. Retrieved {s.retrieved_at}. Fiscal years {s.labels?.[0]}{s.labels && s.labels.length > 1 ? ` - ${s.labels[s.labels.length - 1]}` : ""}; price as of {s.price_date}.</div>
        </Section>
        <Section title="Methodology">
          <ul className="method">{fb.methodology.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </Section>
      </div>
    </div>
  );
}
