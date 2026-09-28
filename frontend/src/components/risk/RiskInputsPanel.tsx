import { useEffect, useMemo, useState } from "react";
import type { RiskInputItem } from "../../types";
import { fmtRisk } from "./riskUtils";

interface Props { items: RiskInputItem[]; busy: boolean; onRebuild: (overrides: Record<string, unknown>) => void; staticMode?: boolean; staticNotice?: string }

const isPct = (fmt: string) => fmt === "pct" || fmt === "pct2" || fmt === "pct4";
const toDisplay = (v: number, fmt: string) => (isPct(fmt) ? +(v * 100).toFixed(fmt === "pct" ? 2 : 4) : fmt === "int" ? Math.round(v) : +v.toFixed(fmt === "num" ? 1 : fmt === "num1" ? 1 : 4));
const fromDisplay = (v: number, fmt: string) => (isPct(fmt) ? v / 100 : v);
const unit = (fmt: string) => (isPct(fmt) ? "%" : fmt === "mult" ? "x" : fmt === "days" ? "days" : "");

/** "Label: 1 = foo, 2 = bar" -> choice options parsed from the label. */
function choices(it: RiskInputItem): { short: string; options: { value: number; label: string }[] } | null {
  if (it.fmt !== "int" || it.min == null || it.max == null || it.max - it.min > 6) return null;
  const re = /(\d+)\s*=\s*([^,;]+?)(?=(?:,\s*\d+\s*=)|$)/g;
  const options: { value: number; label: string }[] = [];
  let m: RegExpExecArray | null;
  const text = it.label;
  while ((m = re.exec(text)) !== null) options.push({ value: Number(m[1]), label: m[2].trim().replace(/\)$/, "") });
  if (options.length < 2) return null;
  const short = text.split(":")[0].trim();
  return { short, options };
}

export function RiskInputsPanel({ items, busy, onRebuild, staticMode, staticNotice }: Props) {
  const [draft, setDraft] = useState<Record<string, number>>({});
  useEffect(() => { setDraft({}); }, [items]);
  const sections = useMemo(() => {
    const m = new Map<string, RiskInputItem[]>();
    for (const it of items) m.set(it.section, [...(m.get(it.section) ?? []), it]);
    return Array.from(m.entries());
  }, [items]);
  const dirty = Object.keys(draft).length;
  const overridden = items.filter((i) => i.overridden).length;
  const current = (it: RiskInputItem) => draft[it.key] ?? it.value;
  const set = (it: RiskInputItem, v: string) => {
    const n = Number(v);
    if (Number.isNaN(n)) return;
    setDraft((d) => ({ ...d, [it.key]: fromDisplay(n, it.fmt) }));
  };
  const outOfRange = (it: RiskInputItem) => { const v = current(it); return (it.min != null && v < it.min) || (it.max != null && v > it.max); };
  const anyBad = items.some(outOfRange);
  const range = (it: RiskInputItem) => {
    if (it.min == null && it.max == null) return "";
    const f = (x: number | null) => (x == null ? "" : isPct(it.fmt) ? `${+(x * 100).toFixed(2)}%` : fmtRisk(x, it.fmt === "int" ? "int" : "general"));
    return `${f(it.min)} - ${f(it.max)}`.replace(/^ - /, "up to ").replace(/ - $/, " or more");
  };

  return (
    <div className="panel inputs-panel">
      <div className="inputs-toolbar">
        <div>
          <b>Inputs</b> - only external data and model choices are inputs; coefficients and thresholds are the published ones. Edit any blue value and rebuild: every sheet, chart and probability is recomputed and the Excel report is re-verified.
          {overridden > 0 && <span className="override-count"> {overridden} input{overridden === 1 ? "" : "s"} currently overridden.</span>}
        </div>
        <div className="toolbar-actions">
          {dirty > 0 && <span className="muted">{dirty} change{dirty === 1 ? "" : "s"} pending</span>}
          <button onClick={() => setDraft({})} disabled={!dirty || busy}>Reset</button>
          <button className="primary big" onClick={() => onRebuild(draft)} disabled={!dirty || busy || anyBad || !!staticMode} title={staticMode ? staticNotice : anyBad ? "Some inputs are outside their allowed range" : undefined}>{busy ? "Rebuilding..." : "Rebuild analysis"}</button>
        </div>
      </div>
      {staticMode && <div className="static-banner">{staticNotice}</div>}
      {sections.map(([section, its]) => (
        <div className="asm-section" key={section}>
          <h4>{section}</h4>
          <table className="asm-table inputs-table">
            <thead><tr><th>Input</th><th>Value</th><th>Allowed range</th><th>Basis</th></tr></thead>
            <tbody>
              {its.map((it) => {
                const ch = choices(it);
                const bad = outOfRange(it);
                return (
                  <tr key={it.key} className={draft[it.key] !== undefined ? "dirty" : it.overridden ? "overridden" : ""}>
                    <td className="asm-label">{ch ? ch.short : it.label}{it.help && <div className="help">{it.help}</div>}{it.overridden && <span className="ovr-pill">override</span>}</td>
                    <td className="asm-inputs">
                      {ch ? (
                        <select value={Math.round(current(it))} onChange={(e) => set(it, e.target.value)} className="choice">
                          {ch.options.map((o) => <option key={o.value} value={o.value}>{o.value} - {o.label}</option>)}
                        </select>
                      ) : (
                        <span className={`inp${bad ? " bad" : ""}`}><input type="number" step="any" value={toDisplay(current(it), it.fmt)} min={it.min != null ? toDisplay(it.min, it.fmt) : undefined} max={it.max != null ? toDisplay(it.max, it.fmt) : undefined} onChange={(e) => set(it, e.target.value)} aria-label={it.label} />{unit(it.fmt)}</span>
                      )}
                      {bad && <div className="bad-text small">outside the allowed range</div>}
                    </td>
                    <td className="asm-range muted">{ch ? `${it.min} - ${it.max}` : range(it)}</td>
                    <td className="asm-basis">{it.basis}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      {dirty > 0 && (
        <div className="inputs-footer">
          <span className="muted">{dirty} change{dirty === 1 ? "" : "s"} pending</span>
          <button className="primary big" onClick={() => onRebuild(draft)} disabled={busy || anyBad || !!staticMode}>{busy ? "Rebuilding..." : "Rebuild analysis"}</button>
        </div>
      )}
    </div>
  );
}
