import { useEffect, useState } from "react";
import { api } from "./api";
import { AssumptionsPanel } from "./components/AssumptionsPanel";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { SearchBar } from "./components/SearchBar";
import { SheetGrid } from "./components/SheetGrid";
import { SummaryCards } from "./components/SummaryCards";
import type { ModelResponse, Provider } from "./types";

const STEPS = ["Resolving company", "Fetching financial statements and prices", "Deriving assumptions", "Building linked three-statement model, beta, WACC and DCF", "Writing Excel workbook", "Verifying every formula with LibreOffice"];

export default function App() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [provider, setProvider] = useState("yahoo");
  const [years, setYears] = useState(5);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState<ModelResponse | null>(null);
  const [tab, setTab] = useState("Overview");

  useEffect(() => {
    api.providers().then((r) => { setProviders(r.providers); setProvider(r.default); }).catch((e) => setError(String(e.message)));
  }, []);

  useEffect(() => {
    if (!busy) return;
    setStep(0);
    const t = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1300);
    return () => window.clearInterval(t);
  }, [busy]);

  const run = async (fn: () => Promise<ModelResponse>) => {
    setBusy(true); setError(null);
    try { const m = await fn(); setModel(m); setTab("Overview"); }
    catch (e: any) { setError(e.message ?? String(e)); }
    finally { setBusy(false); }
  };
  const build = (q: string) => run(() => api.build(q, provider, years));
  const rebuild = (overrides: Record<string, unknown>, yrs: number) => { if (model) run(() => api.rebuild(model.id, overrides, yrs)); };

  const PANELS = ["Overview", "Checks & feedback", "Edit assumptions"];
  const tabs = model ? [...PANELS, ...(model.sheets?.map((s) => s.name) ?? [])] : [];
  const sheet = model?.sheets?.find((s) => s.name === tab);

  return (
    <div className="app">
      <header>
        <div className="brand"><span className="logo">Fin</span>Tea <span className="tag">financial model builder</span></div>
        <div className="brand-sub">Type a company. Get a fully linked three-statement DCF model in Excel - every number a formula, every assumption explained, every formula verified.</div>
      </header>
      <main>
        <SearchBar providers={providers} provider={provider} setProvider={setProvider} years={years} setYears={setYears} busy={busy} onBuild={build} />
        {busy && (
          <div className="progress">
            <div className="spinner" />
            <ol>{STEPS.map((s, i) => <li key={s} className={i < step ? "done" : i === step ? "active" : ""}>{s}</li>)}</ol>
          </div>
        )}
        {error && <div className="error">{error}</div>}
        {model && !busy && (
          <>
            <div className="model-head">
              <div>
                <h2>{model.summary.company} <span className="sym">{model.summary.symbol}</span></h2>
                <div className="muted">{model.summary.source} · {model.summary.units} · historical {model.summary.labels[0]}–{model.summary.labels[model.meta.nh - 1]} · projections to {model.summary.labels[model.summary.labels.length - 1]}</div>
              </div>
              <div className="downloads">
                <a className="button primary" href={model.download_url} download>Download Excel model</a>
                {model.verification.status === "verified" && (
                  <a className="button" href={`${model.download_url}?recalculated=1`} download title="Same workbook re-saved with cached values so previews (mail, Drive, phone) show numbers without recalculating">Download with cached values</a>
                )}
              </div>
            </div>
            <SummaryCards s={model.summary} />
            <nav className="tabs">
              {tabs.map((t, i) => <button key={t} className={(t === tab ? "active" : "") + (i === PANELS.length ? " first-sheet" : "")} onClick={() => setTab(t)}>{t}</button>)}
            </nav>
            {tab === "Overview" && (
              <div className="overview">
                <div className={`status-line ${model.feedback.n_fail > 0 ? "fail" : model.feedback.n_flag > 0 ? "flag" : "pass"}`}>
                  {model.feedback.status} · {model.verification.status === "verified" ? `${model.verification.cells_checked.toLocaleString()} formulas independently verified` : `formula verification ${model.verification.status}`}
                </div>
                <div className="overview-cols">
                  <div>
                    <h3>What is in the workbook</h3>
                    <ul>
                      <li><b>Cover</b> - key outputs, sheet index and colour legend.</li>
                      <li><b>Assumptions</b> - every input (blue) next to the historical ratio it was derived from and a written basis.</li>
                      <li><b>Historicals</b> - reported statements from {model.summary.source} in {model.summary.units}.</li>
                      <li><b>Income Statement, Balance Sheet, Cash Flow</b> - {model.meta.nh} actual years plus {model.meta.np} projected years, fully linked; cash from the cash flow statement closes the balance sheet.</li>
                      <li><b>Beta</b> - monthly regression versus {model.summary.index} with SLOPE/RSQ, Blume adjustment, unlever/relever.</li>
                      <li><b>WACC</b> and <b>DCF</b> - CAPM cost of equity, unlevered FCF, Gordon and exit-multiple terminal values, equity bridge, implied share price.</li>
                      <li><b>Sensitivity</b> - live price grids over WACC × terminal growth and WACC × exit multiple.</li>
                      <li><b>Ratios</b> and <b>Feedback</b> - ratio analysis, formula-driven integrity checks, Altman Z, Piotroski F, and the qualitative assessment.</li>
                    </ul>
                  </div>
                  <div>
                    <h3>Qualitative summary</h3>
                    {model.feedback.qualitative.slice(0, 4).map((s) => (
                      <p key={s.title}><b>{s.title}.</b> {s.points.join(" ")}</p>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {tab === "Checks & feedback" && <FeedbackPanel feedback={model.feedback} verification={model.verification} llm={model.llm} />}
            {tab === "Edit assumptions" && <AssumptionsPanel items={model.assumptions.items} years={model.assumptions.years} labels={model.meta.labels} busy={busy} onRebuild={rebuild} />}
            {sheet && <SheetGrid key={sheet.name} sheet={sheet} />}
          </>
        )}
        {!model && !busy && (
          <div className="welcome">
            <h3>How it works</h3>
            <ol>
              <li>Search a listed company by name or ticker. Data comes from the selected source (Yahoo Finance is free; Bloomberg, FMP and Alpha Vantage plug in with credentials).</li>
              <li>FinTea normalises the statements, derives every assumption from the history (with a written basis), regresses beta, builds WACC, a three-statement forecast and a DCF.</li>
              <li>The Excel workbook is written with live formulas only - then recalculated independently in LibreOffice and compared cell-by-cell to the engine.</li>
              <li>Review the sheets and feedback here, tweak assumptions, rebuild, and download.</li>
            </ol>
          </div>
        )}
      </main>
      <footer>FinTea · models are generated from public data and mechanical assumptions; they are a starting point for analysis, not investment advice.</footer>
    </div>
  );
}
