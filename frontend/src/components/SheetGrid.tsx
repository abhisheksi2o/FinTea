import { useMemo, useState } from "react";
import { colLetter, fmtValue } from "../format";
import type { Cell, Sheet } from "../types";

export function SheetGrid({ sheet }: { sheet: Sheet }) {
  const [sel, setSel] = useState<{ r: number; cell: Cell } | null>(null);
  const grid = useMemo(() => {
    const m = new Map<number, Map<number, Cell>>();
    for (const row of sheet.rows) m.set(row.r, new Map(row.cells.map((c) => [c.c, c])));
    return m;
  }, [sheet]);
  const cols = Array.from({ length: sheet.max_col }, (_, i) => i + 1);
  const rows = Array.from({ length: sheet.max_row }, (_, i) => i + 1);
  const width = (c: number) => `${Math.round((sheet.col_widths[String(c)] ?? (c === 1 ? 44 : 13)) * 7)}px`;

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
                    const cell = rowCells?.get(c);
                    if (!cell) return <td key={c} className="empty" />;
                    const isText = typeof cell.v === "string";
                    const cls = ["cell", `s-${cell.s}`, isText ? "text" : "num", cell.b ? "bold" : "", cell.f ? "has-f" : "",
                      sel?.r === r && sel.cell.c === c ? "selected" : ""].join(" ");
                    return (
                      <td key={c} className={cls} style={{ paddingLeft: cell.i && c === 1 ? `${8 + cell.i * 10}px` : undefined }}
                        title={cell.f ?? undefined} onClick={() => setSel({ r, cell })}>
                        {cell.err ?? fmtValue(cell.v, cell.fmt)}
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
