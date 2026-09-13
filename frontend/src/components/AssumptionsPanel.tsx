import { useEffect, useMemo, useState } from "react";
import type { AssumptionItem } from "../types";

interface Props { items: AssumptionItem[]; years: number; labels: string[]; busy: boolean; onRebuild: (overrides: Record<string, unknown>, years: number) => void; staticMode?: boolean }

const isPct = (fmt: string) => fmt === "pct" || fmt === "pct2";
const toDisplay = (v: number, fmt: string) => (isPct(fmt) ? +(v * 100).toFixed(fmt === "pct2" ? 3 : 2) : +v.toFixed(fmt === "num" ? 1 : 4));
const fromDisplay = (v: number, fmt: string) => (isPct(fmt) ? v / 100 : v);
const unit = (fmt: string) => (isPct(fmt) ? "%" : fmt === "mult" ? "x" : fmt === "days" ? "days" : "");

export function AssumptionsPanel({ items, years, labels, busy, onRebuild, staticMode }: Props) {
  const [draft, setDraft] = useState<Record<string, number | number[]>>({});
  const [yrs, setYrs] = useState(years);
  useEffect(() => { setDraft({}); setYrs(years); }, [items, years]);
  const sections = useMemo(() => {
    const m = new Map<string, AssumptionItem[]>();
    for (const it of items) m.set(it.section, [...(m.get(it.section) ?? []), it]);
    return Array.from(m.entries());
  }, [items]);
  const projLabels = labels.slice(labels.length - years);
  const dirty = Object.keys(draft).length > 0 || yrs !== years;

  const current = (it: AssumptionItem) => draft[it.key] ?? it.value;
  const setScalar = (it: AssumptionItem, v: string) => {
    const n = Number(v);
    if (Number.isNaN(n)) return;
    setDraft((d) => ({ ...d, [it.key]: fromDisplay(n, it.fmt) }));
  };
  const setVec = (it: AssumptionItem, j: number, v: string) => {
    const n = Number(v);
    if (Number.isNaN(n)) return;
    const arr = [...(current(it) as number[])];
    arr[j] = fromDisplay(n, it.fmt);
    setDraft((d) => ({ ...d, [it.key]: arr }));
  };

  return (
    <div className="assumptions">
      <div className="assumptions-toolbar">
        <div>
          <b>Assumptions</b> - blue values are inputs. Edit any of them and rebuild; {staticMode ? "every sheet is recalculated in your browser and the edited model can be downloaded as Excel (the written narrative stays as in the base case)" : "the Excel model and every sheet update"}. The basis column records how each default was derived.
        </div>
        <div className="toolbar-actions">
          <label>Projection years <select value={yrs} disabled={!!staticMode} title={staticMode ? "Changing the horizon needs a live build" : undefined} onChange={(e) => setYrs(Number(e.target.value))}>{[3,4,5,6,7,8,9,10].map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
          <button onClick={() => { setDraft({}); setYrs(years); }} disabled={!dirty || busy}>Reset</button>
          <button className="primary" onClick={() => onRebuild(draft, yrs)} disabled={!dirty || busy}>{busy ? "Rebuilding..." : "Rebuild model"}</button>
        </div>
      </div>
      {sections.map(([section, its]) => (
        <div className="asm-section" key={section}>
          <h4>{section}</h4>
          <table className="asm-table">
            <tbody>
              {its.map((it) => (
                <tr key={it.key} className={draft[it.key] !== undefined ? "dirty" : it.overridden ? "overridden" : ""}>
                  <td className="asm-label">{it.label}{it.help && <div className="help">{it.help}</div>}</td>
                  <td className="asm-inputs">
                    {it.kind === "scalar" ? (
                      <span className="inp"><input type="number" step="any" value={toDisplay(current(it) as number, it.fmt)} onChange={(e) => setScalar(it, e.target.value)} />{unit(it.fmt)}</span>
                    ) : (
                      <div className="vec">
                        {(current(it) as number[]).slice(0, yrs).map((v, j) => (
                          <label key={j}><span>{projLabels[j] ?? `Y${j + 1}`}</span>
                            <input type="number" step="any" value={toDisplay(v, it.fmt)} onChange={(e) => setVec(it, j, e.target.value)} />{unit(it.fmt)}</label>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="asm-basis">{it.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
