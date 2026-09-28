import { useMemo, useState } from "react";
import { colLetter, fmtValue } from "../format";
import type { Cell, Sheet } from "../types";

const colNum = (letters: string) => { let n = 0; for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64); return n; };

export function SheetGrid({ sheet }: { sheet: Sheet }) {
  const [sel, setSel] = useState<{ r: number; cell: Cell } | null>(null);
  const grid = useMemo(() => {
    const m = new Map<number, Map<number, Cell>>();
    for (const row of sheet.rows) m.set(row.r, new Map(row.cells.map((c) => [c.c, c])));
    return m;
  }, [sheet]);
  const cols = Array.from({ length: sheet.max_col }, (_, i) => i + 1);
  const rows = Array.from({ length: sheet.max_row }, (_, i) => i + 1);
  const widthPx = (c: number) => Math.round((sheet.col_widths[String(c)] ?? (c === 1 ? 44 : 13)) * 7);
  const width = (c: number) => `${widthPx(c)}px`;
  // horizontal merged ranges (notes and titles spanning several columns) render as one cell so they do not widen column A
  const merges = useMemo(() => {
    const span = new Map<string, number>();
    const covered = new Set<string>();
    for (const m of sheet.merges ?? []) {
      const mm = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(m);
      if (!mm) continue;
      const c1 = colNum(mm[1]), r1 = Number(mm[2]), c2 = colNum(mm[3]), r2 = Number(mm[4]);
      if (r1 !== r2 || c2 <= c1) continue;
      span.set(`${r1}:${c1}`, c2 - c1 + 1);
      for (let c = c1 + 1; c <= c2; c++) covered.add(`${r1}:${c}`);
    }
    return { span, covered };
  }, [sheet]);

  return (
    <div className="grid-wrap">
      <div className="formula-bar">
        <span className="addr">{sel ? `${sheet.name}!${colLetter(sel.cell.c)}${sel.r}` : "Click a cell to inspect its formula"}</span>
        <code className="formula">{sel ? (sel.cell.f ?? (sel.cell.s === "input" ? "hard-coded input" : String(sel.cell.v ?? ""))) : ""}</code>
        {sel && <span className="val">= {sel.cell.err ?? fmtValue(sel.cell.v, sel.cell.fmt)}</span>}
        {sel?.cell.n && <span className="cell-note">{sel.cell.n}</span>}
      </div>
      <div className="grid-scroll">
        <table className="grid">
          <thead>
            <tr><th className="rowhead"></th>{cols.map((c) => <th key={c} style={{ minWidth: width(c) }}>{colLetter(c)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const rowCells = grid.get(r);
              return (
                <tr key={r}>
                  <th className="rowhead">{r}</th>
                  {cols.map((c) => {
                    if (merges.covered.has(`${r}:${c}`)) return null;
                    const cell = rowCells?.get(c);
                    const span = merges.span.get(`${r}:${c}`);
                    if (!cell) return <td key={c} className="empty" colSpan={span} />;
                    const isText = typeof cell.v === "string";
                    const cls = ["cell", `s-${cell.s}`, isText ? "text" : "num", cell.b ? "bold" : "", cell.f ? "has-f" : "", cell.w ? "wrap" : "",
                      sel?.r === r && sel.cell.c === c ? "selected" : ""].join(" ");
                    const text = cell.err ?? fmtValue(cell.v, cell.fmt);
                    // an unmerged text cell may show up to 1.5x its Excel width, then an ellipsis (the full text is in the tooltip)
                    const cap = isText && !span ? Math.max(Math.round(1.5 * widthPx(c)), 300) : undefined;
                    return (
                      <td key={c} className={cls} colSpan={span} style={{ paddingLeft: cell.i && c === 1 ? `${8 + cell.i * 10}px` : undefined }}
                        title={cell.f ?? (isText && text.length > 40 ? text : undefined)} onClick={() => setSel({ r, cell })}>
                        {cap ? <span className="cell-text" style={{ maxWidth: `${cap}px` }}>{text}</span> : text}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
