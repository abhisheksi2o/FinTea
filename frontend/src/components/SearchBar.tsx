import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Provider, SearchResult } from "../types";

interface Props {
  providers: Provider[]; provider: string; setProvider: (p: string) => void;
  years: number; setYears: (y: number) => void; busy: boolean;
  onBuild: (query: string) => void; staticMode?: boolean;
}

export function SearchBar({ providers, provider, setProvider, years, setYears, busy, onBuild, staticMode }: Props) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 2) { setHits([]); return; }
    timer.current = window.setTimeout(() => {
      api.search(q, provider).then((r) => { setHits(r.results); setOpen(true); }).catch(() => setHits([]));
    }, 250);
    return () => window.clearTimeout(timer.current);
  }, [q, provider]);

  const submit = (value: string) => { setOpen(false); if (value.trim()) onBuild(value.trim()); };

  return (
    <div className="search">
      <div className="search-row">
        <div className="search-input-wrap">
          <input
            className="search-input" placeholder={staticMode ? "Search the pre-built companies, e.g. Apple, NVDA, Infosys" : "Type a company name or ticker, e.g. Apple, MSFT, Infosys (INFY.NS)"}
            value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => hits.length && setOpen(true)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(q); if (e.key === "Escape") setOpen(false); }}
            disabled={busy} autoFocus
          />
          {open && hits.length > 0 && (
            <ul className="suggestions" onMouseLeave={() => setOpen(false)}>
              {hits.map((h) => (
                <li key={h.symbol} onMouseDown={() => { setQ(h.symbol); submit(h.symbol); }}>
                  <b>{h.symbol}</b> <span>{h.name}</span> <em>{h.exchange}</em>
                </li>
              ))}
            </ul>
          )}
        </div>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy} title="Data source">
          {providers.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.available}>{p.name}{p.available ? "" : ` (${p.reason})`}</option>
          ))}
        </select>
        <select value={years} onChange={(e) => setYears(Number(e.target.value))} disabled={busy || staticMode} title={staticMode ? "Pre-built models use a 5-year horizon" : "Projection years"}>
          {[3, 4, 5, 6, 7, 8, 9, 10].map((y) => <option key={y} value={y}>{y} yrs</option>)}
        </select>
        <button className="primary" onClick={() => submit(q)} disabled={busy || !q.trim()}>{busy ? "Building..." : "Build model"}</button>
      </div>
    </div>
  );
}
