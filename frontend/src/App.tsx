import { useEffect, useState } from "react";
import { api, STATIC } from "./api";
import { exportWorkbook, loadIndex, type SiteIndex } from "./staticMode";
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
  const [index, setIndex] = useState<SiteIndex | null>(null);
  const [exporting, setExporting] = useState(false);
  const [country, setCountry] = useState("All");
  const [idxFilter, setIdxFilter] = useState("All");
  const [gridQuery, setGridQuery] = useState("");

  useEffect(() => {
    api.providers().then((r) => { setProviders(r.providers); setProvider(r.default); }).catch((e) => setError(String(e.message)));
    if (STATIC) loadIndex().then(setIndex).catch((e) => setError(String(e.message)));
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
  const rebuild = (overrides: Record<string, unknown>, yrs: number) => { if (model) run(() => api.rebuild(model, model.parent_id ?? model.id, overrides, yrs)); };
  const downloadEdited = async () => {
    if (!model) return;
    setExporting(true);
    try {
      const blob = await exportWorkbook(model);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `FinTea_${model.summary.symbol}_model_${model.summary.base_year}${model.parent_id ? "_edited" : ""}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e: any) { setError(e.message ?? String(e)); }
    finally { setExporting(false); }
  };

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
        {STATIC && (
          <div className="static-banner">
            <b>Hosted on GitHub Pages.</b> {index ? `${index.models.length.toLocaleString()} companies across ${index.countries.length} markets pre-built (refreshed nightly, last ${index.generated}).` : "Loading the model index..."} Pick one below or search. Every model is fully formula-linked; assumption edits are recalculated in your browser and the workbook is written on download. For live builds of any other listed company, run the app from the <a href="https://github.com/abhisheksi2o/FinTea" target="_blank" rel="noreferrer">GitHub repository</a>.
          </div>
        )}
        <SearchBar providers={providers} provider={provider} setProvider={setProvider} years={years} setYears={setYears} busy={busy} onBuild={build} staticMode={STATIC} />
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
                {model.client_generated ? (
                  <button className="primary" onClick={downloadEdited} disabled={exporting}>{exporting ? "Writing workbook..." : (model.parent_id ? "Download edited Excel model" : "Download Excel model")}</button>
                ) : (
                  <a className="button primary" href={model.download_url} download>Download Excel model</a>
                )}
                {!STATIC && model.verification.status === "verified" && (
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
                  {model.feedback.status} · {model.verification.status === "verified" ? `${model.verification.cells_checked.toLocaleString()} formulas independently verified by LibreOffice` : model.verification.status === "browser" ? "recalculated in your browser from the verified base model" : `formula verification ${model.verification.status}`}
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
            {tab === "Edit assumptions" && <AssumptionsPanel items={model.assumptions.items} years={model.assumptions.years} labels={model.meta.labels} busy={busy} onRebuild={rebuild} staticMode={STATIC} />}
            {sheet && <SheetGrid key={sheet.name} sheet={sheet} />}
          </>
        )}
        {!model && !busy && STATIC && index && (() => {
          const q = gridQuery.trim().toLowerCase();
          const list = index.models.filter((m) => (country === "All" || m.country === country) && (idxFilter === "All" || m.index.includes(idxFilter))
            && (!q || m.symbol.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || (m.sector ?? "").toLowerCase().includes(q)));
          const shown = list.slice(0, 96);
          return (
            <div className="browse">
              <div className="browse-bar">
                <select value={country} onChange={(e) => setCountry(e.target.value)}>
                  <option value="All">All markets ({index.models.length})</option>
                  {index.countries.map((c) => <option key={c} value={c}>{c} ({index.models.filter((m) => m.country === c).length})</option>)}
                </select>
                <select value={idxFilter} onChange={(e) => setIdxFilter(e.target.value)}>
                  <option value="All">All indices</option>
                  {index.indices.map((i) => <option key={i} value={i}>{i}</option>)}
                </select>
                <input className="browse-search" placeholder="Filter by name, symbol or sector" value={gridQuery} onChange={(e) => setGridQuery(e.target.value)} />
                <span className="muted">Showing {shown.length} of {list.length}</span>
              </div>
              <div className="company-grid">
                {shown.map((m) => (
                  <button key={m.symbol} className="company" onClick={() => build(m.symbol)} title={m.sector}>
                    <div className="company-sym">{m.symbol} <span className="company-tag">{m.country}</span>{m.financial && <span className="company-tag fin">financial</span>}</div>
                    <div className="company-name">{m.name}</div>
                    <div className={`company-up ${m.implied_price > 0 && m.upside >= 0 ? "good" : "bad"}`}>{m.currency} {m.price.toLocaleString(undefined, { maximumFractionDigits: 2 })} → {m.implied_price.toLocaleString(undefined, { maximumFractionDigits: 2 })} ({(m.upside * 100).toFixed(0)}%)</div>
                  </button>
                ))}
              </div>
            </div>
          );
        })()}
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
