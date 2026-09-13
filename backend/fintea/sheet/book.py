"""In-memory workbook: cells hold either literal values or Expr formulas.

The Book is the single source of truth for the model. It is evaluated lazily
(with memoisation and cycle detection), rendered to openpyxl by
``fintea.excel.writer`` and serialised to JSON for the web preview.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openpyxl.utils import get_column_letter

from .expr import Err, Expr, CellRef

FIRST_PERIOD_COL = 3  # column C holds the first period on statement sheets

# fmt codes -> Excel number formats
FORMATS = {
    "num": '#,##0;(#,##0);"-"',
    "num1": '#,##0.0;(#,##0.0);"-"',
    "num2": '#,##0.00;(#,##0.00);"-"',
    "pct": '0.0%;(0.0%);"-"',
    "pct2": '0.00%;(0.00%);"-"',
    "mult": '0.0"x";(0.0"x");"-"',
    "price": '#,##0.00',
    "int": '#,##0',
    "days": '0.0',
    "date": 'dd-mmm-yyyy',
    "text": '@',
    "general": 'General',
    "factor": '0.0000',
    "beta": '0.000',
}

# style codes: input (blue, hardcoded), formula (black), link (green, cross-sheet),
# total, subtotal, header, section, label, title, subtitle, note, check
STYLES = ("input", "formula", "link", "total", "header", "section", "label",
          "title", "subtitle", "note", "check", "text", "memo", "flag")


@dataclass
class Cell:
    sheet: str
    row: int
    col: int
    content: Any  # Expr or literal
    fmt: str = "general"
    style: str = "formula"
    key: Optional[str] = None
    period: Optional[int] = None
    note: Optional[str] = None
    bold: bool = False
    italic: bool = False
    indent: int = 0
    hyperlink: Optional[str] = None
    wrap: bool = False

    @property
    def is_formula(self) -> bool:
        return isinstance(self.content, Expr)

    @property
    def address(self) -> str:
        return f"{get_column_letter(self.col)}{self.row}"


@dataclass
class Sheet:
    name: str
    cells: Dict[Tuple[int, int], Cell] = field(default_factory=dict)
    col_widths: Dict[int, float] = field(default_factory=dict)
    freeze: Optional[str] = None
    tab_color: Optional[str] = None
    max_row: int = 0
    max_col: int = 0
    row_heights: Dict[int, float] = field(default_factory=dict)
    merges: List[str] = field(default_factory=list)
    period_cols: Dict[int, int] = field(default_factory=dict)  # period -> col
    group_rows: List[Tuple[int, int]] = field(default_factory=list)

    def rows(self):
        return range(1, self.max_row + 1)


class CycleError(RuntimeError):
    pass


class Book:
    def __init__(self):
        self.sheets: Dict[str, Sheet] = {}
        self.order: List[str] = []
        self.registry: Dict[Tuple[str, str, Optional[int]], Tuple[int, int]] = {}
        self._vals: Dict[Tuple[str, int, int], Any] = {}
        self._stack: set = set()
        self.meta: Dict[str, Any] = {}

    # -- structure ---------------------------------------------------------
    def sheet(self, name: str) -> Sheet:
        if name not in self.sheets:
            self.sheets[name] = Sheet(name)
            self.order.append(name)
        return self.sheets[name]

    def set(self, sheet: str, row: int, col: int, content: Any, fmt: str = "general",
            style: str = "formula", key: Optional[str] = None, period: Optional[int] = None,
            **kw) -> Cell:
        sh = self.sheet(sheet)
        if isinstance(content, Expr) and style == "input":
            raise ValueError(f"input cells must be literals: {sheet}!{row},{col}")
        cell = Cell(sheet, row, col, content, fmt, style, key, period, **kw)
        sh.cells[(row, col)] = cell
        sh.max_row = max(sh.max_row, row)
        sh.max_col = max(sh.max_col, col)
        if key is not None:
            rk = (sheet, key, period)
            if rk in self.registry and self.registry[rk] != (row, col):
                raise ValueError(f"duplicate key {rk}")
            self.registry[rk] = (row, col)
        self._vals.pop((sheet, row, col), None)
        return cell

    def get(self, sheet: str, row: int, col: int) -> Optional[Cell]:
        return self.sheets[sheet].cells.get((row, col)) if sheet in self.sheets else None

    def lookup(self, sheet: str, key: str, period: Optional[int]) -> Tuple[int, int]:
        try:
            return self.registry[(sheet, key, period)]
        except KeyError:
            raise KeyError(f"unknown reference {sheet}!{key}[{period}]") from None

    def has(self, sheet: str, key: str, period: Optional[int] = None) -> bool:
        return (sheet, key, period) in self.registry

    def ref(self, sheet: str, key: str, period: Optional[int] = None) -> CellRef:
        r, c = self.lookup(sheet, key, period)
        return CellRef(sheet, r, c)

    # -- evaluation --------------------------------------------------------
    def value(self, sheet: str, row: int, col: int) -> Any:
        k = (sheet, row, col)
        if k in self._vals:
            return self._vals[k]
        cell = self.get(sheet, row, col)
        if cell is None:
            return None
        if not isinstance(cell.content, Expr):
            v = cell.content
        else:
            if k in self._stack:
                raise CycleError(f"circular reference at {sheet}!{cell.address}")
            self._stack.add(k)
            try:
                v = cell.content.eval(self)
            finally:
                self._stack.discard(k)
        self._vals[k] = v
        return v

    def val(self, sheet: str, key: str, period: Optional[int] = None) -> Any:
        r, c = self.lookup(sheet, key, period)
        return self.value(sheet, r, c)

    def num(self, sheet: str, key: str, period: Optional[int] = None) -> Optional[float]:
        v = self.val(sheet, key, period)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def formula(self, cell: Cell) -> Optional[str]:
        if isinstance(cell.content, Expr):
            return "=" + cell.content.render(self, cell.sheet)
        return None

    def evaluate_all(self) -> Dict[str, int]:
        """Evaluate every cell; returns count of error cells per sheet."""
        errors: Dict[str, int] = {}
        for name in self.order:
            sh = self.sheets[name]
            n = 0
            for (r, c) in list(sh.cells):
                if isinstance(self.value(name, r, c), Err):
                    n += 1
            errors[name] = n
        return errors

    def invalidate(self):
        self._vals.clear()

    # -- serialisation -----------------------------------------------------
    def to_json(self) -> Dict[str, Any]:
        out = {"sheets": [], "meta": self.meta}
        for name in self.order:
            sh = self.sheets[name]
            rows: Dict[int, List[Dict[str, Any]]] = {}
            for (r, c), cell in sorted(sh.cells.items()):
                v = self.value(name, r, c)
                if isinstance(v, Err):
                    jv: Any = None
                    err = v.code
                else:
                    jv, err = v, None
                if isinstance(jv, float) and (jv != jv or jv in (float("inf"), float("-inf"))):
                    jv, err = None, "#NUM!"
                d: Dict[str, Any] = {"c": c, "v": jv, "fmt": cell.fmt, "s": cell.style}
                f = self.formula(cell)
                if f:
                    d["f"] = f
                if err:
                    d["err"] = err
                if cell.key:
                    d["k"] = cell.key
                if cell.bold:
                    d["b"] = True
                if cell.indent:
                    d["i"] = cell.indent
                if cell.note:
                    d["n"] = cell.note
                if cell.hyperlink:
                    d["hl"] = cell.hyperlink
                if cell.wrap:
                    d["w"] = True
                rows.setdefault(r, []).append(d)
            out["sheets"].append({
                "name": name,
                "max_row": sh.max_row,
                "max_col": sh.max_col,
                "col_widths": {str(k): v for k, v in sh.col_widths.items()},
                "period_cols": {str(k): v for k, v in sh.period_cols.items()},
                "merges": list(sh.merges),
                "freeze": sh.freeze,
                "tab_color": sh.tab_color,
                "row_heights": {str(k): v for k, v in sh.row_heights.items()},
                "rows": [{"r": r, "cells": cells} for r, cells in sorted(rows.items())],
            })
        return out
