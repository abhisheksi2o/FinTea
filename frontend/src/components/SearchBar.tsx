import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Provider, RiskBasis, SearchResult } from "../types";

export type AppMode = "dcf" | "risk";

interface Props {
  providers: Provider[]; provider: string; setProvider: (p: string) => void;
  years: number; setYears: (y: number) => void; busy: boolean;
  onSubmit: (query: string) => void; staticMode?: boolean;
  mode: AppMode; setMode: (m: AppMode) => void;
  basis?: RiskBasis; setBasis?: (b: RiskBasis) => void;
}

interface Recent { q: string; name?: string; exchange?: string; at: number }
type Item = { kind: "hit"; hit: SearchResult } | { kind: "recent"; recent: Recent } | { kind: "raw"; q: string };

const RECENT_KEY = "fintea.recentSearches";
const MAX_RECENT = 8;
const loadRecent = (): Recent[] => {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((r) => r && typeof r.q === "string").slice(0, MAX_RECENT) : [];
  } catch { return []; }
};
const saveRecent = (r: Recent[]) => { try { localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, MAX_RECENT))); } catch { /* private mode etc. */ } };

const EXAMPLES: { label: string; q: string; staticOnly?: boolean; liveOnly?: boolean }[] = [
  { label: "Apple", q: "AAPL" }, { label: "Microsoft", q: "MSFT" }, { label: "Tesla", q: "TSLA" },
  { label: "Reliance Industries", q: "RELIANCE.NS" }, { label: "Beyond Meat", q: "BYND" },
  { label: "NVIDIA", q: "NVDA", staticOnly: true }, { label: "HDFC Bank", q: "HDFCBANK.NS" },
];

export const MODE_LABEL: Record<AppMode, { name: string; action: string; busy: string; blurb: string }> = {
  dcf: { name: "Financial model (DCF)", action: "Build model", busy: "Building...", blurb: "Linked three-statement forecast, beta, WACC, DCF and sensitivities - every number an Excel formula." },
  risk: { name: "Default risk analysis", action: "Analyse default risk", busy: "Analysing...", blurb: "Altman, Ohlson, Zmijewski, Piotroski, Beneish, Springate, Grover, Taffler, Merton and a synthetic rating in one verified Excel report." },
};

/** Highlight the query inside a suggestion label. */
function Hi({ text, q }: { text: string; q: string }) {
  const needle = q.trim().toLowerCase();
  const i = needle ? text.toLowerCase().indexOf(needle) : -1;
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + needle.length)}</mark>{text.slice(i + needle.length)}</>;
}

export function SearchBar({ providers, provider, setProvider, years, setYears, busy, onSubmit, staticMode, mode, setMode, basis = "ltm", setBasis }: Props) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState("");          // the query the current `hits` belong to
  const [searchError, setSearchError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [recent, setRecent] = useState<Recent[]>(loadRecent);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const reqId = useRef(0);
  const listId = useId();
  const labels = MODE_LABEL[mode];
  const trimmed = q.trim();
  const searching = trimmed.length >= 2;

  // ------------------------------------------------------------ debounced autocomplete
  useEffect(() => {
    if (!searching) { setHits([]); setLoading(false); setSearchError(null); setSearched(""); return; }
    const id = ++reqId.current;
    const ctrl = new AbortController();
    setLoading(true);
    const t = window.setTimeout(() => {
      api.search(trimmed, provider, ctrl.signal)
        .then((r) => { if (id !== reqId.current) return; setHits(r.results ?? []); setSearched(trimmed); setSearchError(null); })
        .catch((e: any) => { if (id !== reqId.current || e?.name === "AbortError") return; setHits([]); setSearched(trimmed); setSearchError(e?.message ?? String(e)); })
        .finally(() => { if (id === reqId.current) setLoading(false); });
    }, 220);
    return () => { window.clearTimeout(t); ctrl.abort(); };
  }, [trimmed, provider, searching]);

  // close on outside click
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const items: Item[] = useMemo(() => {
    if (searching) {
      const list: Item[] = hits.map((hit) => ({ kind: "hit", hit }));
      // the raw query is only useful where a data source can resolve it; the pre-built site has nothing beyond its index
      if (!staticMode && !loading && searched === trimmed && !hits.some((h) => h.symbol.toLowerCase() === trimmed.toLowerCase())) list.push({ kind: "raw", q: trimmed });
      return list;
    }
    return recent.map((recent) => ({ kind: "recent", recent }));
  }, [searching, hits, loading, searched, trimmed, recent]);

  useEffect(() => { setActive(-1); }, [items.length, trimmed]);

  // keep the active option in view
  useEffect(() => {
    if (active < 0 || !listRef.current) return;
    const el = listRef.current.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const remember = useCallback((entry: Recent) => {
    setRecent((prev) => {
      const next = [entry, ...prev.filter((r) => r.q.toLowerCase() !== entry.q.toLowerCase())].slice(0, MAX_RECENT);
      saveRecent(next);
      return next;
    });
  }, []);

  const submit = useCallback((value: string, meta?: { name?: string; exchange?: string }) => {
    const v = value.trim();
    if (!v || busy) return;
    setOpen(false); setActive(-1); setQ(v);
    remember({ q: v, name: meta?.name, exchange: meta?.exchange, at: Date.now() });
    onSubmit(v);
  }, [busy, onSubmit, remember]);

  const choose = (it: Item) => {
    if (it.kind === "hit") submit(it.hit.symbol, { name: it.hit.name, exchange: it.hit.exchange });
    else if (it.kind === "recent") submit(it.recent.q, { name: it.recent.name, exchange: it.recent.exchange });
    else submit(it.q);
  };

  const removeRecent = (r: Recent) => {
    setRecent((prev) => { const next = prev.filter((x) => x.q !== r.q); saveRecent(next); return next; });
  };
  const clearRecent = () => { setRecent([]); saveRecent([]); };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      if (items.length) setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      if (items.length) setActive((a) => (a <= 0 ? items.length - 1 : a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && active >= 0 && items[active]) choose(items[active]);
      else submit(q);
    } else if (e.key === "Escape") {
      if (open) { e.preventDefault(); setOpen(false); setActive(-1); }
      else if (q) { setQ(""); }
    } else if (e.key === "Tab") {
      setOpen(false);
    } else if (e.key === "Home" && open && items.length) { e.preventDefault(); setActive(0); }
    else if (e.key === "End" && open && items.length) { e.preventDefault(); setActive(items.length - 1); }
  };

  const showList = open && !busy && (searching || items.length > 0);
  const examples = EXAMPLES.filter((x) => (staticMode ? !x.liveOnly : !x.staticOnly));
  const optId = (i: number) => `${listId}-opt-${i}`;

  return (
    <div className="search" role="search">
      <div className="search-top">
        <div className="mode-switch" role="tablist" aria-label="Analysis type">
          {(["dcf", "risk"] as AppMode[]).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} className={mode === m ? "on" : ""} onClick={() => setMode(m)} disabled={busy}>
              <span className={`mode-dot ${m}`} aria-hidden="true" />{MODE_LABEL[m].name}
            </button>
          ))}
        </div>
        <div className="mode-blurb">{labels.blurb}</div>
      </div>
      <div className="search-row">
        <div className="search-input-wrap" ref={wrapRef}>
          <svg className="search-icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
          <input
            ref={inputRef}
            className="search-input"
            type="text"
            role="combobox"
            aria-label="Company name or ticker"
            aria-autocomplete="list"
            aria-expanded={showList}
            aria-controls={listId}
            aria-haspopup="listbox"
            aria-activedescendant={showList && active >= 0 ? optId(active) : undefined}
            autoComplete="off" spellCheck={false}
            placeholder={staticMode ? "Search the pre-built companies, e.g. Apple, NVDA, Infosys" : "Company name or ticker, e.g. Apple, MSFT, Reliance, INFY.NS"}
            value={q}
            onChange={(e) => { setQ(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            disabled={busy}
            autoFocus
          />
          {loading && <span className="search-spinner" aria-label="Searching" role="status" />}
          {q && !loading && (
            <button type="button" className="search-clear" aria-label="Clear search" onMouseDown={(e) => e.preventDefault()} onClick={() => { setQ(""); setOpen(true); inputRef.current?.focus(); }}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
            </button>
          )}
          {showList && (
            <div className="suggestions" onMouseLeave={() => setActive(-1)}>
              {!searching && items.length > 0 && (
                <div className="sug-head"><span>Recent searches</span><button type="button" className="linkish" onMouseDown={(e) => e.preventDefault()} onClick={clearRecent}>Clear</button></div>
              )}
              {searching && loading && hits.length === 0 && <div className="sug-status">Searching {providers.find((p) => p.id === provider)?.name ?? "the data source"}...</div>}
              {searching && !loading && searchError && <div className="sug-status bad-text">Search unavailable: {searchError}</div>}
              {searching && !loading && !searchError && searched === trimmed && hits.length === 0 && (
                <div className="sug-empty">
                  <b>No listed company matches &ldquo;{trimmed}&rdquo;</b>
                  <span>Try the ticker with its exchange suffix (INFY.NS, SAP.DE, 7203.T) or a distinctive part of the name.</span>
                </div>
              )}
              <ul className="sug-list" role="listbox" id={listId} ref={listRef} aria-label={searching ? "Matching companies" : "Recent searches"}>
                {items.map((it, i) => {
                  const cls = `sug ${it.kind}${i === active ? " active" : ""}`;
                  const common = { role: "option", id: optId(i), "aria-selected": i === active, "data-idx": i, className: cls,
                    onMouseEnter: () => setActive(i), onMouseDown: (e: React.MouseEvent) => e.preventDefault(), onClick: () => choose(it) } as const;
                  if (it.kind === "hit") {
                    const h = it.hit;
                    const meta = [h.exchange, [h.sector, h.industry].filter(Boolean).join(" / "), h.type && h.type !== "EQUITY" ? h.type : ""].filter(Boolean);
                    return (
                      <li key={`h-${h.symbol}-${i}`} {...common}>
                        <span className="sug-sym"><Hi text={h.symbol} q={trimmed} /></span>
                        <span className="sug-main">
                          <span className="sug-name"><Hi text={h.name || h.symbol} q={trimmed} /></span>
                          <span className="sug-meta">{meta.map((m, j) => <span key={j}>{m}</span>)}</span>
                        </span>
                        <span className="sug-go" aria-hidden="true">{labels.action} &rarr;</span>
                      </li>
                    );
                  }
                  if (it.kind === "recent") {
                    const r = it.recent;
                    return (
                      <li key={`r-${r.q}`} {...common}>
                        <span className="sug-sym clock" aria-hidden="true"><svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" /><path d="M10 6v4.5l3 1.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg></span>
                        <span className="sug-main">
                          <span className="sug-name"><b>{r.q}</b>{r.name && r.name !== r.q ? <span className="sug-dim"> &middot; {r.name}</span> : null}</span>
                          {r.exchange && <span className="sug-meta"><span>{r.exchange}</span></span>}
                        </span>
                        <button type="button" className="sug-remove" aria-label={`Remove ${r.q} from recent searches`} title="Remove"
                          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }} onClick={(e) => { e.stopPropagation(); removeRecent(r); }}>
                          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                        </button>
                      </li>
                    );
                  }
                  return (
                    <li key="raw" {...common}>
                      <span className="sug-sym" aria-hidden="true">&crarr;</span>
                      <span className="sug-main"><span className="sug-name">Use &ldquo;{it.q}&rdquo; as typed</span><span className="sug-meta"><span>{mode === "risk" ? "Analyse" : "Build"} whatever the data source resolves this to</span></span></span>
                    </li>
                  );
                })}
              </ul>
              <div className="sug-foot"><kbd>&uarr;</kbd><kbd>&darr;</kbd> navigate &nbsp; <kbd>Enter</kbd> {searching && !staticMode ? "select or search as typed" : "select"} &nbsp; <kbd>Esc</kbd> close</div>
            </div>
          )}
        </div>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy} title="Data source" aria-label="Data source">
          {providers.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.available}>{p.name}{p.available ? "" : ` (${p.reason})`}</option>
          ))}
        </select>
        {mode === "dcf" && (
          <select value={years} onChange={(e) => setYears(Number(e.target.value))} disabled={busy || staticMode} aria-label="Projection years" title={staticMode ? "Pre-built models use a 5-year horizon" : "Projection years"}>
            {[3, 4, 5, 6, 7, 8, 9, 10].map((y) => <option key={y} value={y}>{y} yrs</option>)}
          </select>
        )}
        {mode === "risk" && (
          <select value={basis} onChange={(e) => setBasis?.(e.target.value as RiskBasis)} disabled={busy || staticMode} aria-label="Statement basis"
            title={staticMode ? "Pre-built reports use the latest twelve months wherever the quarterly statements allow it" : "Which statements the latest column uses: the last four quarters (latest twelve months) or the last fiscal year"}>
            <option value="ltm">Latest 12 months</option>
            <option value="annual">Latest fiscal year</option>
          </select>
        )}
        <button type="button" className={`primary go ${mode}`} onClick={() => submit(q)} disabled={busy || !trimmed}>{busy ? labels.busy : labels.action}</button>
      </div>
      <div className="examples" aria-label="Examples">
        <span className="examples-label">Try</span>
        {examples.map((x) => (
          <button key={x.q} type="button" className="chip" disabled={busy} title={x.q} onClick={() => submit(x.q, { name: x.label })}>{x.label}</button>
        ))}
      </div>
    </div>
  );
}
