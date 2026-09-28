import { useCallback, useEffect, useState } from "react";
import { api, REPO_URL, STATIC, STATIC_RISK_NOTICE } from "./api";
import { exportWorkbook, loadIndex, type SiteIndex } from "./staticMode";
import { AssumptionsPanel } from "./components/AssumptionsPanel";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { SearchBar, type AppMode } from "./components/SearchBar";
import { SheetGrid } from "./components/SheetGrid";
import { SummaryCards } from "./components/SummaryCards";
import { RiskView } from "./components/risk/RiskView";
import type { ModelResponse, Provider, RiskBasis, RiskResponse } from "./types";

const DCF_STEPS = ["Resolving company", "Fetching financial statements and prices", "Deriving assumptions", "Building linked three-statement model, beta, WACC and DCF", "Writing Excel workbook", "Verifying every formula with LibreOffice"];
const RISK_STEPS = ["Resolving company", "Fetching statements, prices and rates", "Computing Altman, Ohlson, Zmijewski, Piotroski, Beneish, Springate, Grover and Taffler", "Solving the Merton model and the synthetic rating", "Writing the Excel report", "Verifying every formula with LibreOffice"];

const MODE_KEY = "fintea.mode";
const loadMode = (): AppMode => { try { return localStorage.getItem(MODE_KEY) === "risk" ? "risk" : "dcf"; } catch { return "dcf"; } };
const BASIS_KEY = "fintea.risk.basis";
const loadBasis = (): RiskBasis => { try { return localStorage.getItem(BASIS_KEY) === "annual" ? "annual" : "ltm"; } catch { return "ltm"; } };
const GRADE_ORDER: Record<string, number> = { Severe: 0, High: 1, Moderate: 2, Low: 3, Minimal: 4 };

export default function App() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [provider, setProvider] = useState("yahoo");
  const [years, setYears] = useState(5);
  const [mode, setModeState] = useState<AppMode>(loadMode);
  const [basis, setBasisState] = useState<RiskBasis>(loadBasis);
  const [busy, setBusy] = useState(false);
  const [busyMode, setBusyMode] = useState<AppMode>("dcf");
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState<ModelResponse | null>(null);
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [tab, setTab] = useState("Overview");
  const [index, setIndex] = useState<SiteIndex | null>(null);
  const [exporting, setExporting] = useState(false);
  const [country, setCountry] = useState("All");
  const [idxFilter, setIdxFilter] = useState("All");
  const [gridQuery, setGridQuery] = useState("");

  const setMode = useCallback((m: AppMode) => { setModeState(m); setError(null); try { localStorage.setItem(MODE_KEY, m); } catch { /* ignore */ } }, []);
  const setBasis = useCallback((b: RiskBasis) => { setBasisState(b); try { localStorage.setItem(BASIS_KEY, b); } catch { /* ignore */ } }, []);

  useEffect(() => {
    api.providers().then((r) => { setProviders(r.providers); setProvider(r.default); }).catch((e) => setError(String(e.message)));
    if (STATIC) loadIndex().then(setIndex).catch((e) => setError(String(e.message)));
  }, []);

  const steps = busyMode === "risk" ? RISK_STEPS : DCF_STEPS;
  useEffect(() => {
    if (!busy) return;
    setStep(0);
    const t = window.setInterval(() => setStep((s) => Math.min(s + 1, steps.length - 1)), 1300);
    return () => window.clearInterval(t);
  }, [busy, steps.length]);

  const run = async (fn: () => Promise<ModelResponse>) => {
    setBusy(true); setBusyMode("dcf"); setError(null);
    try { const m = await fn(); setModel(m); setTab("Overview"); }
    catch (e: any) { setError(e.message ?? String(e)); }
    finally { setBusy(false); }
  };
  const runRisk = async (fn: () => Promise<RiskResponse>) => {
    setBusy(true); setBusyMode("risk"); setError(null);
    try { setRisk(await fn()); }
    catch (e: any) { setError(e.message ?? String(e)); }
    finally { setBusy(false); }
  };
  const build = (q: string) => run(() => api.build(q, provider, years));
  const rebuild = (overrides: Record<string, unknown>, yrs: number) => { if (model) run(() => api.rebuild(model, model.parent_id ?? model.id, overrides, yrs)); };
  const analyse = (q: string, b: RiskBasis = basis) => runRisk(() => api.risk(q, provider, b));
  const rebuildRisk = (overrides: Record<string, unknown>) => { if (risk) runRisk(() => api.riskRebuild(risk.id, overrides, basis)); };
  /** Switch between the latest-twelve-months and fiscal-year basis and re-run the same company. */
  const switchBasis = (b: RiskBasis) => { setBasis(b); if (risk) analyse(risk.summary.symbol, b); };
  const submit = (q: string) => (mode === "risk" ? analyse(q) : build(q));

  const saveBlob = (blob: Blob, filename: string) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  };
  const downloadEdited = async () => {
    if (!model) return;
    setExporting(true);
    try { saveBlob(await exportWorkbook(model), `FinTea_${model.summary.symbol}_model_${model.summary.base_year}${model.parent_id ? "_edited" : ""}.xlsx`); }
    catch (e: any) { setError(e.message ?? String(e)); }
    finally { setExporting(false); }
  };
  const downloadRisk = async () => {
    if (!risk) return;
    setExporting(true);
    try { saveBlob(await exportWorkbook(risk), `FinTea_${risk.summary.symbol}_default_risk_${(risk.summary.base_label ?? String(risk.summary.base_year)).replace(/\s+/g, "_")}.xlsx`); }
    catch (e: any) { setError(e.message ?? String(e)); }
    finally { setExporting(false); }
  };

  const PANELS = ["Overview", "Checks & feedback", "Edit assumptions"];
  const sheet = tab.startsWith("sheet:") ? model?.sheets?.find((s) => `sheet:${s.name}` === tab) : undefined;
  const showDcf = mode === "dcf" && model && !busy;
  const showRisk = mode === "risk" && risk && !busy;

  return (
    <div className={`app mode-${mode}`}>
      <header>
        <div className="brand"><span className="logo">Fin</span>Tea <span className="tag">financial models &amp; default risk analytics</span></div>
        <div className="brand-sub">Type a company. Get a fully linked three-statement DCF model or a multi-model default risk report in Excel - every number a formula, every assumption explained, every formula verified.</div>
      </header>
      <main>
        {STATIC && (
          <div className="static-banner">
            <b>Pre-built static site.</b> {index ? `${index.models.length.toLocaleString()} companies across ${index.countries.length} markets pre-built (refreshed nightly on GitHub Pages; this copy was generated ${index.generated}).` : "Loading the model index..."} Pick one below or search. Every model is fully formula-linked; assumption edits are recalculated in your browser and the workbook is written on download. For live builds of any other listed company, run the app from the <a href={REPO_URL} target="_blank" rel="noreferrer">GitHub repository</a>.
          </div>
        )}
        <SearchBar providers={providers} provider={provider} setProvider={setProvider} years={years} setYears={setYears} busy={busy} onSubmit={submit} staticMode={STATIC} mode={mode} setMode={setMode} basis={basis} setBasis={setBasis} />
        {STATIC && mode === "risk" && !risk && !busy && (
          <div className="notice risk-static">
            <b>Pre-built default-risk reports.</b> {index ? `${(index.risk_count ?? index.models.filter((m) => m.risk).length).toLocaleString()} of the ${index.models.length.toLocaleString()} companies on this site have a report` : "The report index is loading"}, refreshed nightly on the latest-twelve-months basis where the quarterly statements allow it. Pick a company below or search. To analyse any other listed company, or to edit inputs and rebuild, run the app from the <a href={REPO_URL} target="_blank" rel="noreferrer">GitHub repository</a>.
          </div>
        )}
        {busy && (
          <div className="progress" role="status" aria-live="polite">
            <div className="spinner" />
            <div>
              <div className="progress-title">{busyMode === "risk" ? "Analysing default risk" : "Building the financial model"}</div>
              <ol>{steps.map((s, i) => <li key={s} className={i < step ? "done" : i === step ? "active" : ""}>{s}</li>)}</ol>
            </div>
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}

        {showRisk && risk && <RiskView r={risk} busy={busy} staticMode={STATIC} staticNotice={STATIC_RISK_NOTICE} onRebuild={rebuildRisk} onBasis={STATIC ? undefined : switchBasis} onExport={risk.download_url ? undefined : downloadRisk} exporting={exporting} />}

        {showDcf && model && (
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
            <nav className="tabs" aria-label="Model sections">
              {PANELS.map((t) => <button key={`panel-${t}`} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
              <span className="tabs-group-label" aria-hidden="true">Excel sheets</span>
              {(model.sheets ?? []).map((sh) => (
                <button key={`sheet-${sh.name}`} className={`sheet-tab${`sheet:${sh.name}` === tab ? " active" : ""}`} onClick={() => setTab(`sheet:${sh.name}`)} title={`${sh.name} sheet of the workbook`}>
                  <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M1.5 6.5h13M1.5 10h13M6 2.5v11M10.5 2.5v11" stroke="currentColor" strokeWidth="1" /></svg>{sh.name}
                </button>
              ))}
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
                    <p className="muted">Want the credit view? Switch to <button className="linkish" onClick={() => setMode("risk")}>Default risk analysis</button> and run the same company.</p>
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
            {tab === "Checks & feedback" && <FeedbackPanel feedback={model.feedback} verification={model.verification} llm={model.llm} model={model} />}
            {tab === "Edit assumptions" && <AssumptionsPanel items={model.assumptions.items} years={model.assumptions.years} labels={model.meta.labels} busy={busy} onRebuild={rebuild} staticMode={STATIC} />}
            {sheet && <SheetGrid key={sheet.name} sheet={sheet} />}
          </>
        )}

        {mode === "dcf" && !model && !busy && STATIC && index && (() => {
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

        {mode === "risk" && !risk && !busy && STATIC && index && (() => {
          const q = gridQuery.trim().toLowerCase();
          const list = index.models.filter((m) => (country === "All" || m.country === country) && (idxFilter === "All" || m.index.includes(idxFilter))
            && (!q || m.symbol.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || (m.sector ?? "").toLowerCase().includes(q)));
          const sorted = [...list].sort((a, b) => (a.risk ? GRADE_ORDER[a.risk.grade] ?? 9 : 9) - (b.risk ? GRADE_ORDER[b.risk.grade] ?? 9 : 9) || (b.risk?.score ?? -1) - (a.risk?.score ?? -1) || a.symbol.localeCompare(b.symbol));
          const shown = sorted.slice(0, 96);
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
                <span className="muted">Showing {shown.length} of {list.length}, highest distress signal first</span>
              </div>
              <div className="company-grid">
                {shown.map((m) => (
                  <button key={m.symbol} className={`company risk-card${m.risk ? "" : " missing"}`} onClick={() => analyse(m.symbol)} disabled={!m.risk} title={m.risk ? `${m.sector} · ${m.risk.basis}${m.risk.rating ? ` · synthetic rating ${m.risk.rating}` : ""}` : "No pre-built report for this company"}>
                    <div className="company-sym">{m.symbol} <span className="company-tag">{m.country}</span>{m.financial && <span className="company-tag fin">financial</span>}</div>
                    <div className="company-name">{m.name}</div>
                    {m.risk ? (
                      <div className="company-risk">
                        <span className={`grade grade-${m.risk.grade.toLowerCase()}`}>{m.risk.grade}</span>
                        <span className="muted">{Math.round(m.risk.score)}/100 · PD {m.risk.pd != null ? `${(m.risk.pd * 100).toFixed(m.risk.pd < 0.01 ? 2 : 1)}%` : "n/a"}{m.risk.ltm ? " · LTM" : ""}</span>
                      </div>
                    ) : <div className="company-risk muted">no report</div>}
                  </button>
                ))}
              </div>
            </div>
          );
        })()}

        {mode === "dcf" && !model && !busy && (
          <div className="welcome">
            <h3>How the financial model works</h3>
            <ol>
              <li>Search a listed company by name or ticker. Data comes from the selected source (Yahoo Finance is free; Bloomberg, FMP and Alpha Vantage plug in with credentials).</li>
              <li>FinTea normalises the statements, derives every assumption from the history (with a written basis), regresses beta, builds WACC, a three-statement forecast and a DCF.</li>
              <li>The Excel workbook is written with live formulas only - then recalculated independently in LibreOffice and compared cell-by-cell to the engine.</li>
              <li>Review the sheets and feedback here, tweak assumptions, rebuild, and download.</li>
            </ol>
          </div>
        )}
        {mode === "risk" && !risk && !busy && (
          <div className="welcome risk-welcome">
            <div className="welcome-grid">
              <div>
                <h3>How the default risk analysis works</h3>
                <ol>
                  <li>Search a listed company. FinTea fetches the reported statements, the share price history, the risk-free rate and the market capitalisation.</li>
                  <li>It computes the classic accounting models - Altman Z / Z' / Z'', Ohlson O, Zmijewski X, Springate, Grover, Taffler - plus Piotroski F and the Beneish M earnings-quality screen, each with the published coefficients and cut-offs.</li>
                  <li>It solves the Merton structural model for a market-implied probability of default (naive distance to default and the iterated two-equation solve), maps interest coverage to a synthetic bond rating with its historical default rates, and runs simple stress scenarios.</li>
                  <li>Everything is written to an Excel report as live formulas linked to the blue input cells, recalculated independently in LibreOffice and compared cell by cell. Edit inputs here and rebuild.</li>
                </ol>
              </div>
              <div className="welcome-side">
                <h4>What you get</h4>
                <ul>
                  <li>Probabilities of default from three independent families: market-implied (Merton), accounting (Ohlson, Zmijewski) and rating-implied (historical default rates).</li>
                  <li>Model agreement: how many of the distress models flag the company, with each verdict.</li>
                  <li>Trends of leverage, coverage and liquidity, and ten charts that also live in the Excel dashboard.</li>
                  <li>A data-quality audit: 25 formula-driven checks, model applicability and the verification result.</li>
                </ul>
                <p className="muted small">Nothing here is investment advice or a credit rating; it is a mechanical screen from public data.</p>
              </div>
            </div>
          </div>
        )}
      </main>
      <footer>FinTea · models and risk analyses are generated from public data and mechanical assumptions; they are a starting point for analysis, not investment advice or a credit rating.</footer>
    </div>
  );
}
