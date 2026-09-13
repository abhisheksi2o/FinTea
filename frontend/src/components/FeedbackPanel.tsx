import { fmtValue } from "../format";
import type { Feedback, ModelResponse, Verification } from "../types";

export function FeedbackPanel({ feedback, verification, llm }: { feedback: Feedback; verification: Verification; llm: ModelResponse["llm"] }) {
  return (
    <div className="feedback">
      <div className={`status-banner ${feedback.n_fail > 0 ? "fail" : feedback.n_flag > 0 ? "flag" : "pass"}`}>
        <b>{feedback.status}</b>
        <span>{feedback.n_fail} integrity failure(s), {feedback.n_flag} assumption flag(s)</span>
      </div>
      <div className="verify">
        {verification.status === "verified" && (
          <span className="ok">Formula verification: {verification.cells_checked.toLocaleString()} formula cells recalculated by {verification.engine} match the model engine (max difference {verification.max_abs_diff?.toExponential(1)}).</span>
        )}
        {verification.status === "mismatch" && (
          <span className="bad">Formula verification found {verification.n_mismatches} mismatching cell(s), e.g. {verification.mismatches[0]?.sheet}!{verification.mismatches[0]?.cell}.</span>
        )}
        {verification.status === "skipped" && <span className="warn">Formula verification skipped: {verification.reason}</span>}
      </div>
      <h3>Quantitative checks</h3>
      <table className="checks">
        <thead><tr><th>Check</th><th>Value</th><th>Threshold</th><th>Status</th><th>Why it matters</th></tr></thead>
        <tbody>
          {feedback.quantitative.map((q) => (
            <tr key={q.check} className={q.status.toLowerCase()}>
              <td>{q.check}</td><td className="num">{fmtValue(q.value, q.fmt)}</td><td>{q.threshold}</td>
              <td><span className={`pill ${q.status.toLowerCase()}`}>{q.status}</span></td><td className="why">{q.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Qualitative assessment</h3>
      {feedback.qualitative.map((s) => (
        <div className="qual" key={s.title}>
          <h4>{s.title}</h4>
          <ul>{s.points.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </div>
      ))}
      {llm && llm.status === "ok" && (
        <div className="qual ai">
          <h4>AI analyst commentary <span className="muted">({llm.model})</span></h4>
          {llm.text?.split(/\n+/).map((p, i) => <p key={i}>{p}</p>)}
        </div>
      )}
      {llm && llm.status === "error" && <p className="muted">AI commentary unavailable: {llm.error}</p>}
      <h3>Methodology</h3>
      <ul className="method">{feedback.methodology.map((m, i) => <li key={i}>{m}</li>)}</ul>
    </div>
  );
}
