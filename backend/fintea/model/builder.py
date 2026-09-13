"""Build the complete financial model as a formula-driven Book.

Sheet order: Cover, Assumptions, Historicals, Income Statement, Balance Sheet,
Cash Flow, Beta, WACC, DCF, Sensitivity, Ratios, Feedback.

Columns C.. on statement sheets hold fiscal periods: first the historical
years (A), then the projection years (E). Every projected number is a formula
that traces back to the Assumptions sheet and the Historicals sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from ..providers.base import FIELD_LABELS, FinancialDataset
from ..sheet import (ABS, AND, AVERAGE, CORREL, COUNT, COVAR, GE, GT, IF, IFERROR, INTERCEPT, LE, LT, MAX, MIN, OR,
                     RSQ, SLOPE, SQRT, STDEV, SUM, VARP, EQ, Book, CellRef, Expr, K, RangeK, RangeRef, FIRST_PERIOD_COL)
from .assumptions import ASSUMPTION_SPECS, Assumptions, derive_assumptions

M = 1e6
COVER, ASSUMP, HIST, IS, BS, CF, BETA, WACC, DCF, SENS, RATIOS, FEED = (
    "Cover", "Assumptions", "Historicals", "Income Statement", "Balance Sheet", "Cash Flow",
    "Beta", "WACC", "DCF", "Sensitivity", "Ratios", "Feedback")
SHEET_ORDER = [COVER, ASSUMP, HIST, IS, BS, CF, BETA, WACC, DCF, SENS, RATIOS, FEED]
TAB_COLORS = {COVER: "1F3864", ASSUMP: "2E75B6", HIST: "7F7F7F", IS: "548235", BS: "548235", CF: "548235",
              BETA: "BF8F00", WACC: "BF8F00", DCF: "C55A11", SENS: "C55A11", RATIOS: "7030A0", FEED: "C00000"}


@dataclass
class ModelResult:
    book: Book
    dataset: FinancialDataset
    assumptions: Assumptions
    summary: Dict[str, Any]
    feedback: Dict[str, Any]


def _style_for(content: Any, sheet: str) -> str:
    if not isinstance(content, Expr):
        return "input"
    if isinstance(content, K) and content.sheet != sheet:
        return "link"
    if isinstance(content, CellRef) and content.sheet != sheet:
        return "link"
    return "formula"


class SB:
    """Cursor-based helper to lay a sheet out row by row."""

    def __init__(self, book: Book, name: str, periods: List[int], labels: List[str], dates: List[str], nh: int,
                 first_period: int = 0):
        self.book, self.name, self.periods, self.labels, self.dates, self.nh = book, name, periods, labels, dates, nh
        self.first_period = first_period  # period index shown in column C
        self.sh = book.sheet(name)
        self.sh.tab_color = TAB_COLORS.get(name)
        self.r = 1
        for p in periods:
            self.sh.period_cols[p] = self.col(p)

    def col(self, p: int) -> int:
        return FIRST_PERIOD_COL + p - self.first_period

    def title(self, text: str, sub: str = "") -> None:
        self.book.set(self.name, 1, 1, text, "text", "title")
        if sub:
            self.book.set(self.name, 2, 1, sub, "text", "subtitle")
        self.r = 4

    def header(self, label: str = "", units: str = "") -> None:
        """Period header (FY labels) + period-end dates row."""
        self.book.set(self.name, self.r, 1, label or "Fiscal year", "text", "header")
        self.book.set(self.name, self.r, 2, units, "text", "header")
        for p in self.periods:
            self.book.set(self.name, self.r, self.col(p), self.labels[p], "text", "header")
        self.r += 1
        self.book.set(self.name, self.r, 1, "Period end", "text", "note")
        for p in self.periods:
            self.book.set(self.name, self.r, self.col(p), self.dates[p], "text", "note")
        self.sh.freeze = f"C{self.r + 1}"
        self.r += 1

    def section(self, text: str) -> None:
        self.r += 1
        self.book.set(self.name, self.r, 1, text, "text", "section")
        self.r += 1

    def blank(self, n: int = 1) -> None:
        self.r += n

    def row(self, key: Optional[str], label: str, fn: Callable[[int], Any], fmt: str = "num",
            periods: Optional[List[int]] = None, style: Optional[str] = None, bold: bool = False,
            indent: int = 1, note: Optional[str] = None, memo: bool = False) -> int:
        r = self.r
        self.book.set(self.name, r, 1, label, "text", "memo" if memo else ("total" if bold else "label"),
                      bold=bold, indent=indent)
        if note:
            self.book.set(self.name, r, 2, note, "text", "note")
        for p in (periods if periods is not None else self.periods):
            content = fn(p)
            if content is None:
                continue
            st = style or _style_for(content, self.name)
            if bold and st == "formula":
                st = "total"
            self.book.set(self.name, r, self.col(p), content, fmt, st, key=key, period=p, bold=bold)
        self.r += 1
        return r

    def scalar(self, key: Optional[str], label: str, content: Any, fmt: str = "num", basis: str = "",
               style: Optional[str] = None, bold: bool = False, col: int = 2) -> int:
        r = self.r
        self.book.set(self.name, r, 1, label, "text", "total" if bold else "label", bold=bold, indent=1)
        if content is not None:
            st = style or _style_for(content, self.name)
            self.book.set(self.name, r, col, content, fmt, st, key=key, period=None, bold=bold)
        if basis:
            self.book.set(self.name, r, col + 1, basis, "text", "note", wrap=False)
        self.r += 1
        return r

    def text(self, text: str, style: str = "text", col: int = 1, wrap: bool = False, bold: bool = False,
             merge_to: Optional[int] = None, chars_per_line: int = 190) -> int:
        r = self.r
        self.book.set(self.name, r, col, text, "text", style, wrap=wrap, bold=bold)
        if merge_to:
            from openpyxl.utils import get_column_letter as _gcl
            self.sh.merges.append(f"{_gcl(col)}{r}:{_gcl(merge_to)}{r}")
            lines = max(1, -(-len(text) // chars_per_line))
            self.sh.row_heights[r] = 14.5 * lines + 2
        self.r += 1
        return r


def _fy_label(year: int, actual: bool) -> str:
    return f"FY{year}{'A' if actual else 'E'}"


def build_model(ds: FinancialDataset, assumptions: Optional[Assumptions] = None, years: int = 5,
                overrides: Optional[Dict[str, Any]] = None) -> ModelResult:
    A = assumptions or derive_assumptions(ds, years, overrides)
    N = A.years
    nh = len(ds.periods)
    H = list(range(nh))                 # historical period indices
    P = list(range(nh, nh + N))         # projection period indices
    ALL = H + P
    L = nh - 1                          # base year (last actual)
    base_year = ds.periods[L].fiscal_year
    labels = [_fy_label(p.fiscal_year, True) for p in ds.periods] + [_fy_label(base_year + j + 1, False) for j in range(N)]
    end = ds.periods[L].period_end
    dates = [p.period_end for p in ds.periods] + [f"{base_year + j + 1}{end[4:]}" for j in range(N)]
    ccy = ds.profile.currency
    units = f"{ccy} millions"
    book = Book()
    book.meta = {"company": ds.profile.name, "symbol": ds.profile.symbol, "currency": ccy, "units": units,
                 "labels": labels, "dates": dates, "nh": nh, "np": N, "source": ds.source,
                 "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
    for s in SHEET_ORDER:
        book.sheet(s).tab_color = TAB_COLORS[s]

    def a(key: str, p: Optional[int] = None) -> K:
        return K(ASSUMP, key, p)

    def h(key: str, p: int) -> K:
        return K(HIST, key, p)

    def isr(key: str, p: int) -> K:
        return K(IS, key, p)

    def bsr(key: str, p: int) -> K:
        return K(BS, key, p)

    def cfr(key: str, p: int) -> K:
        return K(CF, key, p)

    def hist_or(hist_fn, proj_fn):
        return lambda p: hist_fn(p) if p < nh else proj_fn(p)

    # =====================================================================
    # Cover
    # =====================================================================
    cv = SB(book, COVER, [], labels, dates, nh)
    cv.title("FinTea Financial Model", f"{ds.profile.name} ({ds.profile.symbol})")
    cv.text("Model overview", "section")
    for lab, val in (("Company", ds.profile.name), ("Ticker", ds.profile.symbol), ("Exchange", ds.profile.exchange or "n/a"),
                     ("Reporting currency", ccy), ("Units", f"{units} (shares in millions, per-share data in {ccy})"),
                     ("Data source", ds.source), ("Data retrieved", ds.retrieved_at.replace("T", " ").replace("Z", " UTC")),
                     ("Share price as of", ds.market.price_date), ("Fiscal year end", end[5:]),
                     ("Historical years", f"{labels[0]} - {labels[L]}"), ("Projection years", f"{labels[nh]} - {labels[-1]}"),
                     ("Model generated", book.meta["generated"])):
        cv.scalar(None, lab, val, "text", style="text")
    cv.blank()
    cv.text("Key outputs", "section")
    cv.scalar("cover_price", "Current share price", a("price"), "price")
    cv.scalar("cover_implied", "Implied share price (DCF)", K(DCF, "implied_price"), "price", bold=True)
    cv.scalar("cover_upside", "Upside / (downside) to current price", K(DCF, "upside"), "pct", bold=True)
    cv.scalar("cover_ev", f"Enterprise value ({units})", K(DCF, "enterprise_value"), "num")
    cv.scalar("cover_eq", f"Equity value ({units})", K(DCF, "equity_value"), "num")
    cv.scalar("cover_wacc", "WACC", K(WACC, "wacc"), "pct2")
    cv.scalar("cover_beta", "Selected beta", K(BETA, "selected_beta"), "beta")
    cv.scalar("cover_tg", "Terminal growth", a("terminal_growth"), "pct2")
    cv.scalar("cover_checks", "Model integrity checks", K(FEED, "overall_status"), "text")
    cv.blank()
    cv.text("Sheet index", "section")
    toc = {IS: "Historical and projected P&L", BS: "Historical and projected balance sheet (balances by construction)",
           CF: "Cash flow statement; ending cash feeds the balance sheet", ASSUMP: "Every input with its derivation basis",
           HIST: "Raw reported data from the source, in millions", BETA: "Regression beta, Blume adjustment, unlever/relever",
           WACC: "Cost of equity (CAPM), cost of debt, weights", DCF: "Unlevered free cash flow, terminal value, equity bridge",
           SENS: "Implied share price sensitivity tables", RATIOS: "Growth, margins, returns, liquidity, leverage",
           FEED: "Quantitative checks and qualitative assessment"}
    for s in [ASSUMP, HIST, IS, BS, CF, BETA, WACC, DCF, SENS, RATIOS, FEED]:
        r = cv.r
        book.set(COVER, r, 1, s, "text", "label", hyperlink=f"#'{s}'!A1", indent=1)
        book.set(COVER, r, 2, toc[s], "text", "note")
        cv.r += 1
    cv.blank()
    cv.text("Colour legend", "section")
    book.set(COVER, cv.r, 1, "Hard-coded input (blue on yellow) - change these", "text", "input"); cv.r += 1
    book.set(COVER, cv.r, 1, "Calculation (black) - formula within the sheet", "text", "formula"); cv.r += 1
    book.set(COVER, cv.r, 1, "Link (green) - pulls from another sheet", "text", "link"); cv.r += 1
    book.set(COVER, cv.r, 1, "Total / subtotal", "text", "total"); cv.r += 1
    cv.sh.col_widths = {1: 44, 2: 70}

    # =====================================================================
    # Historicals (raw inputs)
    # =====================================================================
    hs = SB(book, HIST, H, labels, dates, nh)
    hs.title("Historical data (as reported)", f"{ds.profile.name} - {units}; source: {ds.source}")
    hs.header("Reported line item", "Source field")

    def raw(key: str, scale: float = M):
        return lambda p: (ds.periods[p].fields.get(key) or 0.0) / scale

    groups = [("Income statement", ["revenue", "cogs", "gross_profit", "sga", "rnd", "opex_total", "operating_income", "da",
                                    "interest_expense", "interest_income", "pretax_income", "tax", "net_income", "ebitda"]),
              ("Share data", ["diluted_shares", "basic_shares", "shares_outstanding", "diluted_eps"]),
              ("Balance sheet", ["cash", "cash_and_sti", "receivables", "inventory", "current_assets", "ppe",
                                 "goodwill_intangibles", "total_assets", "payables", "short_term_debt", "current_liabilities",
                                 "long_term_debt", "total_liabilities", "total_equity", "stockholders_equity",
                                 "retained_earnings", "total_debt"]),
              ("Cash flow statement", ["cfo", "da_cf", "sbc", "change_wc", "capex", "cfi", "cff", "dividends", "buybacks",
                                       "stock_issued", "debt_issued", "debt_repaid", "begin_cash", "end_cash",
                                       "net_change_cash", "free_cash_flow"])]
    for title, keys in groups:
        hs.section(title)
        for k in keys:
            scale = 1.0 if k == "diluted_eps" else M
            fmt = "price" if k == "diluted_eps" else ("num1" if "shares" in k else "num")
            src = ds.periods[L].source_fields.get(k, "")
            hs.row(k, FIELD_LABELS[k], raw(k, scale), fmt, style="input", note=src)
    hs.blank()
    hs.text("All values are hard-coded inputs taken from the data source; the statements sheets link to these cells.", "note")
    hs.sh.col_widths = {1: 44, 2: 40}

    # =====================================================================
    # Assumptions
    # =====================================================================
    asb = SB(book, ASSUMP, ALL, labels, dates, nh)
    asb.title("Assumptions", f"{ds.profile.name} - blue cells are inputs; the basis column explains each derivation")
    asb.text("Scalar inputs", "section")
    book.set(ASSUMP, asb.r, 1, "Input", "text", "header"); book.set(ASSUMP, asb.r, 2, "Value", "text", "header")
    book.set(ASSUMP, asb.r, 3, "Basis / derivation", "text", "header"); asb.r += 1
    scalar_specs = [s for s in ASSUMPTION_SPECS if s.kind == "scalar"]
    current_section = None
    for s in scalar_specs:
        if s.section != current_section:
            current_section = s.section
            book.set(ASSUMP, asb.r, 1, s.section, "text", "subtitle", bold=True); asb.r += 1
        asb.scalar(s.key, s.label, A.values[s.key], s.fmt, basis=A.basis.get(s.key, ""), style="input")
    asb.blank()
    asb.text("Derived market metrics", "section")
    asb.scalar("market_cap", f"Market capitalisation ({units})", a("price") * a("shares_outstanding"), "num",
               basis="Share price x shares outstanding")
    asb.scalar("base_total_debt", f"Total debt at FY{base_year} ({units})", K(BS, "total_debt", L), "num", basis="Balance Sheet")
    asb.scalar("base_cash", f"Cash & short-term investments at FY{base_year} ({units})", K(BS, "cash_sti", L), "num", basis="Balance Sheet")
    asb.scalar("enterprise_value_market", f"Market enterprise value ({units})",
               a("market_cap") + a("base_total_debt") - a("base_cash"), "num", basis="Market cap + debt - cash")
    asb.scalar("ev_ebitda_ltm", "EV / LTM EBITDA (market)", IFERROR(a("enterprise_value_market") / K(IS, "ebitda", L), 0), "mult",
               basis="Market EV / last fiscal year EBITDA")
    asb.scalar("pe_ltm", "P / E (LTM, market)", IFERROR(a("price") / K(IS, "eps", L), 0), "mult", basis="Price / last fiscal year diluted EPS")
    asb.blank()
    asb.text("Operating drivers by year (historical columns show the actual ratio; projection columns are inputs)", "section")
    asb.header("Driver", "")
    vec_specs = [s for s in ASSUMPTION_SPECS if s.kind == "vector"]
    hist_ratio = {
        "rev_growth": lambda p: IFERROR(isr("revenue", p) / isr("revenue", p - 1) - 1, 0) if p > 0 else None,
        "gross_margin": lambda p: IFERROR(isr("gross_profit", p) / isr("revenue", p), 0),
        "sga_pct": lambda p: IFERROR(isr("sga", p) / isr("revenue", p), 0),
        "rnd_pct": lambda p: IFERROR(isr("rnd", p) / isr("revenue", p), 0),
        "other_opex_pct": lambda p: IFERROR(isr("other_opex", p) / isr("revenue", p), 0),
        "da_pct": lambda p: IFERROR(isr("da", p) / bsr("ppe", p - 1), 0) if p > 0 else None,
        "capex_pct": lambda p: IFERROR(-cfr("capex", p) / isr("revenue", p), 0),
        "sbc_pct": lambda p: IFERROR(cfr("sbc", p) / isr("revenue", p), 0),
        "other_nonop": lambda p: isr("other_nonop", p),
        "net_debt_issuance": lambda p: cfr("net_debt_issuance", p),
        "buybacks": lambda p: -cfr("buybacks", p),
    }
    basis_col = FIRST_PERIOD_COL + nh + N
    for s in vec_specs:
        vals = A.values[s.key]
        r = asb.row(s.key, s.label, hist_or(hist_ratio[s.key], lambda p, v=vals: float(v[p - nh])), s.fmt)
        book.set(ASSUMP, r, basis_col, A.basis.get(s.key, ""), "text", "note")
    asb.sh.col_widths = {1: 46, 2: 14, basis_col: 90}
    for p in ALL:
        asb.sh.col_widths[FIRST_PERIOD_COL + p] = 12

    # =====================================================================
    # Income Statement
    # =====================================================================
    ist = SB(book, IS, ALL, labels, dates, nh)
    ist.title("Income Statement", f"{ds.profile.name} - {units}")
    ist.header("", units)
    ist.row("revenue", "Revenue", hist_or(lambda p: h("revenue", p), lambda p: isr("revenue", p - 1) * (1 + a("rev_growth", p))), bold=True)
    ist.row("cogs", "Cost of revenue", hist_or(lambda p: h("cogs", p), lambda p: isr("revenue", p) * (1 - a("gross_margin", p))))
    ist.row("gross_profit", "Gross profit", lambda p: isr("revenue", p) - isr("cogs", p), bold=True)
    ist.row("sga", "Selling, general & administrative", hist_or(lambda p: h("sga", p), lambda p: isr("revenue", p) * a("sga_pct", p)))
    ist.row("rnd", "Research & development", hist_or(lambda p: h("rnd", p), lambda p: isr("revenue", p) * a("rnd_pct", p)))
    ist.row("other_opex", "Other operating expenses (incl. reconciling items)",
            hist_or(lambda p: isr("gross_profit", p) - isr("sga", p) - isr("rnd", p) - h("operating_income", p),
                    lambda p: isr("revenue", p) * a("other_opex_pct", p)))
    ist.row("total_opex", "Total operating expenses", lambda p: isr("sga", p) + isr("rnd", p) + isr("other_opex", p), bold=True)
    ist.row("ebit", "Operating income (EBIT)", lambda p: isr("gross_profit", p) - isr("total_opex", p), bold=True)
    ist.row("da", "Depreciation & amortisation", hist_or(lambda p: h("da", p), lambda p: bsr("ppe", p - 1) * a("da_pct", p)),
            note="Projected on opening net PP&E")
    ist.row("ebitda", "EBITDA", lambda p: isr("ebit", p) + isr("da", p), bold=True)
    ist.row("interest_expense", "Interest expense", hist_or(lambda p: h("interest_expense", p),
                                                             lambda p: bsr("total_debt", p - 1) * a("cost_of_debt")),
            note="Projected on opening debt balance")
    ist.row("interest_income", "Interest income", hist_or(lambda p: h("interest_income", p),
                                                           lambda p: bsr("cash_sti", p - 1) * a("cash_yield")),
            note="Projected on opening cash balance")
    ist.row("other_nonop", "Other non-operating income / (expense)",
            hist_or(lambda p: h("pretax_income", p) - (isr("ebit", p) - isr("interest_expense", p) + isr("interest_income", p)),
                    lambda p: a("other_nonop", p)))
    ist.row("ebt", "Pre-tax income", lambda p: isr("ebit", p) - isr("interest_expense", p) + isr("interest_income", p) + isr("other_nonop", p), bold=True)
    ist.row("tax", "Income tax expense", hist_or(lambda p: h("tax", p), lambda p: isr("ebt", p) * a("tax_rate")))
    ist.row("other_ni", "Other (minority interest, discontinued ops)",
            hist_or(lambda p: h("net_income", p) - (isr("ebt", p) - isr("tax", p)), lambda p: 0.0))
    ist.row("net_income", "Net income", lambda p: isr("ebt", p) - isr("tax", p) + isr("other_ni", p), bold=True)
    ist.blank()
    ist.row("diluted_shares", "Diluted weighted-average shares (millions)",
            hist_or(lambda p: h("diluted_shares", p), lambda p: isr("diluted_shares", p - 1) * (1 + a("share_change"))), "num1")
    ist.row("eps", f"Diluted EPS ({ccy})", lambda p: IFERROR(isr("net_income", p) / isr("diluted_shares", p), 0), "price", bold=True)
    ist.section("Memo: growth and margins")
    ist.row("m_rev_growth", "Revenue growth", lambda p: IFERROR(isr("revenue", p) / isr("revenue", p - 1) - 1, 0) if p > 0 else None, "pct", memo=True)
    ist.row("m_gross_margin", "Gross margin", lambda p: IFERROR(isr("gross_profit", p) / isr("revenue", p), 0), "pct", memo=True)
    ist.row("m_ebitda_margin", "EBITDA margin", lambda p: IFERROR(isr("ebitda", p) / isr("revenue", p), 0), "pct", memo=True)
    ist.row("m_ebit_margin", "EBIT margin", lambda p: IFERROR(isr("ebit", p) / isr("revenue", p), 0), "pct", memo=True)
    ist.row("m_net_margin", "Net margin", lambda p: IFERROR(isr("net_income", p) / isr("revenue", p), 0), "pct", memo=True)
    ist.row("m_tax_rate", "Effective tax rate", lambda p: IFERROR(isr("tax", p) / isr("ebt", p), 0), "pct", memo=True)
    ist.row("m_eps_growth", "EPS growth", lambda p: IFERROR(isr("eps", p) / isr("eps", p - 1) - 1, 0) if p > 0 else None, "pct", memo=True)
    ist.sh.col_widths = {1: 46, 2: 26}

    # =====================================================================
    # Balance Sheet
    # =====================================================================
    bst = SB(book, BS, ALL, labels, dates, nh)
    bst.title("Balance Sheet", f"{ds.profile.name} - {units}")
    bst.header("", units)
    bst.section("Assets")
    bst.row("cash", "Cash & cash equivalents", hist_or(lambda p: h("cash", p), lambda p: cfr("end_cash", p)), note="Projection: from Cash Flow")
    bst.row("sti", "Short-term investments", hist_or(lambda p: h("cash_and_sti", p) - h("cash", p), lambda p: bsr("sti", p - 1)), note="Held constant")
    bst.row("receivables", "Accounts receivable", hist_or(lambda p: h("receivables", p), lambda p: isr("revenue", p) * a("dso") / 365), note="Revenue x DSO / 365")
    bst.row("inventory", "Inventory", hist_or(lambda p: h("inventory", p), lambda p: isr("cogs", p) * a("dio") / 365), note="COGS x DIO / 365")
    bst.row("other_ca", "Other current assets",
            hist_or(lambda p: h("current_assets", p) - h("cash_and_sti", p) - h("receivables", p) - h("inventory", p),
                    lambda p: isr("revenue", p) * a("other_ca_pct")), note="% of revenue")
    bst.row("total_current_assets", "Total current assets",
            lambda p: bsr("cash", p) + bsr("sti", p) + bsr("receivables", p) + bsr("inventory", p) + bsr("other_ca", p), bold=True)
    bst.row("ppe", "Net property, plant & equipment", hist_or(lambda p: h("ppe", p), lambda p: bsr("ppe", p - 1) - cfr("capex", p) - isr("da", p)),
            note="Opening + capex - D&A")
    bst.row("goodwill_intangibles", "Goodwill & intangibles", hist_or(lambda p: h("goodwill_intangibles", p), lambda p: bsr("goodwill_intangibles", p - 1)), note="Held constant")
    bst.row("other_nca", "Other non-current assets",
            hist_or(lambda p: h("total_assets", p) - h("current_assets", p) - h("ppe", p) - h("goodwill_intangibles", p),
                    lambda p: isr("revenue", p) * a("other_nca_pct")), note="% of revenue")
    bst.row("total_assets", "Total assets", lambda p: bsr("total_current_assets", p) + bsr("ppe", p) + bsr("goodwill_intangibles", p) + bsr("other_nca", p), bold=True)
    bst.section("Liabilities")
    bst.row("payables", "Accounts payable", hist_or(lambda p: h("payables", p), lambda p: isr("cogs", p) * a("dpo") / 365), note="COGS x DPO / 365")
    bst.row("short_term_debt", "Short-term debt & current leases", hist_or(lambda p: h("short_term_debt", p), lambda p: bsr("short_term_debt", p - 1)), note="Held constant")
    bst.row("other_cl", "Other current liabilities",
            hist_or(lambda p: h("current_liabilities", p) - h("payables", p) - h("short_term_debt", p),
                    lambda p: isr("revenue", p) * a("other_cl_pct")), note="% of revenue")
    bst.row("total_current_liabilities", "Total current liabilities", lambda p: bsr("payables", p) + bsr("short_term_debt", p) + bsr("other_cl", p), bold=True)
    bst.row("long_term_debt", "Long-term debt & leases", hist_or(lambda p: h("long_term_debt", p), lambda p: bsr("long_term_debt", p - 1) + cfr("net_debt_issuance", p)),
            note="Opening + net issuance")
    bst.row("other_ncl", "Other non-current liabilities",
            hist_or(lambda p: h("total_liabilities", p) - h("current_liabilities", p) - h("long_term_debt", p),
                    lambda p: isr("revenue", p) * a("other_ncl_pct")), note="% of revenue")
    bst.row("total_liabilities", "Total liabilities", lambda p: bsr("total_current_liabilities", p) + bsr("long_term_debt", p) + bsr("other_ncl", p), bold=True)
    bst.section("Equity")
    bst.row("total_equity", "Total equity (incl. minority interest)",
            hist_or(lambda p: h("total_assets", p) - h("total_liabilities", p),
                    lambda p: bsr("total_equity", p - 1) + isr("net_income", p) + cfr("dividends", p) + cfr("buybacks", p) + cfr("sbc", p)),
            bold=True, note="Opening + NI - dividends - buybacks + SBC")
    bst.row("total_liabilities_equity", "Total liabilities & equity", lambda p: bsr("total_liabilities", p) + bsr("total_equity", p), bold=True)
    bst.blank()
    bst.row("balance_check", "Balance check (assets - liabilities - equity)", lambda p: bsr("total_assets", p) - bsr("total_liabilities_equity", p), "num2", style="check")
    bst.section("Memo")
    bst.row("total_debt", "Total debt", lambda p: bsr("short_term_debt", p) + bsr("long_term_debt", p), memo=True)
    bst.row("cash_sti", "Cash & short-term investments", lambda p: bsr("cash", p) + bsr("sti", p), memo=True)
    bst.row("net_debt", "Net debt / (net cash)", lambda p: bsr("total_debt", p) - bsr("cash_sti", p), memo=True)
    bst.row("nwc", "Net working capital (ex cash & debt)",
            lambda p: bsr("receivables", p) + bsr("inventory", p) + bsr("other_ca", p) - bsr("payables", p) - bsr("other_cl", p), memo=True)
    bst.sh.col_widths = {1: 46, 2: 30}

    # =====================================================================
    # Cash Flow
    # =====================================================================
    cft = SB(book, CF, ALL, labels, dates, nh)
    cft.title("Cash Flow Statement", f"{ds.profile.name} - {units}")
    cft.header("", units)
    cft.section("Operating activities")
    cft.row("net_income", "Net income", hist_or(lambda p: h("net_income", p), lambda p: isr("net_income", p)))
    cft.row("da", "Depreciation & amortisation", hist_or(lambda p: h("da", p), lambda p: isr("da", p)))
    cft.row("sbc", "Stock-based compensation", hist_or(lambda p: h("sbc", p), lambda p: isr("revenue", p) * a("sbc_pct", p)))
    cft.row("change_wc", "Change in working capital",
            hist_or(lambda p: h("change_wc", p),
                    lambda p: -((bsr("receivables", p) - bsr("receivables", p - 1)) + (bsr("inventory", p) - bsr("inventory", p - 1))
                                + (bsr("other_ca", p) - bsr("other_ca", p - 1)))
                              + ((bsr("payables", p) - bsr("payables", p - 1)) + (bsr("other_cl", p) - bsr("other_cl", p - 1)))),
            note="-(change in AR, inventory, other CA) + change in AP, other CL")
    cft.row("other_operating", "Other operating items",
            hist_or(lambda p: h("cfo", p) - cfr("net_income", p) - cfr("da", p) - cfr("sbc", p) - cfr("change_wc", p),
                    lambda p: (bsr("other_ncl", p) - bsr("other_ncl", p - 1)) - (bsr("other_nca", p) - bsr("other_nca", p - 1))),
            note="Change in other non-current liabilities less assets")
    cft.row("cfo", "Cash from operating activities",
            lambda p: cfr("net_income", p) + cfr("da", p) + cfr("sbc", p) + cfr("change_wc", p) + cfr("other_operating", p), bold=True)
    cft.section("Investing activities")
    cft.row("capex", "Capital expenditure", hist_or(lambda p: h("capex", p), lambda p: -isr("revenue", p) * a("capex_pct", p)))
    cft.row("other_investing", "Other investing (assumed nil)", hist_or(lambda p: h("cfi", p) - cfr("capex", p), lambda p: 0.0))
    cft.row("cfi", "Cash from investing activities", lambda p: cfr("capex", p) + cfr("other_investing", p), bold=True)
    cft.section("Financing activities")
    cft.row("net_debt_issuance", "Net debt issued / (repaid)", hist_or(lambda p: h("debt_issued", p) + h("debt_repaid", p), lambda p: a("net_debt_issuance", p)))
    cft.row("dividends", "Dividends paid", hist_or(lambda p: h("dividends", p), lambda p: -isr("net_income", p) * a("payout_ratio")))
    cft.row("buybacks", "Share repurchases, net of issuance", hist_or(lambda p: h("buybacks", p) + h("stock_issued", p), lambda p: -a("buybacks", p)))
    cft.row("other_financing", "Other financing",
            hist_or(lambda p: h("cff", p) - cfr("net_debt_issuance", p) - cfr("dividends", p) - cfr("buybacks", p), lambda p: 0.0))
    cft.row("cff", "Cash from financing activities", lambda p: cfr("net_debt_issuance", p) + cfr("dividends", p) + cfr("buybacks", p) + cfr("other_financing", p), bold=True)
    cft.blank()
    cft.row("fx_other", "FX and other (assumed nil)", hist_or(lambda p: h("net_change_cash", p) - cfr("cfo", p) - cfr("cfi", p) - cfr("cff", p), lambda p: 0.0))
    cft.row("net_change_cash", "Net change in cash", lambda p: cfr("cfo", p) + cfr("cfi", p) + cfr("cff", p) + cfr("fx_other", p), bold=True)
    cft.row("begin_cash", "Beginning cash", hist_or(lambda p: h("begin_cash", p), lambda p: bsr("cash", p - 1)))
    cft.row("end_cash", "Ending cash", lambda p: cfr("begin_cash", p) + cfr("net_change_cash", p), bold=True)
    cft.row("cash_check", "Ending cash vs balance sheet cash (historical differences = restricted cash)",
            lambda p: cfr("end_cash", p) - bsr("cash", p), "num2", style="check")
    cft.section("Memo")
    cft.row("fcf", "Free cash flow (CFO + capex)", lambda p: cfr("cfo", p) + cfr("capex", p), memo=True)
    cft.row("fcf_margin", "FCF margin", lambda p: IFERROR(cfr("fcf", p) / isr("revenue", p), 0), "pct", memo=True)
    cft.sh.col_widths = {1: 50, 2: 34}

    # =====================================================================
    # Beta
    # =====================================================================
    bt = SB(book, BETA, [], labels, dates, nh)
    sp, ip = ds.stock_prices, ds.index_prices
    n_px = min(len(sp.closes), len(ip.closes))
    bt.title("Beta calculation", f"{ds.profile.symbol} vs {ip.name} ({ip.symbol}) - monthly total returns, {n_px - 1} observations")
    data_r0 = 30
    ret_r0 = data_r0 + 1
    ret_r1 = data_r0 + n_px - 1
    stock_rng = RangeRef(BETA, ret_r0, 4, ret_r1, 4)
    index_rng = RangeRef(BETA, ret_r0, 5, ret_r1, 5)
    bt.text("Regression statistics", "section")
    bt.scalar("n_obs", "Observations (monthly returns)", COUNT(stock_rng), "int", basis="COUNT of monthly return pairs")
    bt.scalar("raw_beta", "Raw regression beta", SLOPE(stock_rng, index_rng), "beta", basis="SLOPE(stock returns, index returns)", bold=True)
    bt.scalar("beta_check", "Beta cross-check (covariance / variance)", COVAR(stock_rng, index_rng) / VARP(index_rng), "beta",
              basis="COVAR(stock, index) / VARP(index) - must equal the slope")
    bt.scalar("alpha", "Alpha (monthly intercept)", INTERCEPT(stock_rng, index_rng), "pct2", basis="INTERCEPT(stock returns, index returns)")
    bt.scalar("r_squared", "R-squared", RSQ(stock_rng, index_rng), "factor", basis="Share of stock variance explained by the index")
    bt.scalar("correl", "Correlation", CORREL(stock_rng, index_rng), "factor")
    bt.scalar("stock_vol", "Stock volatility (annualised)", STDEV(stock_rng) * SQRT(12), "pct", basis="STDEV(monthly) x sqrt(12)")
    bt.scalar("index_vol", "Index volatility (annualised)", STDEV(index_rng) * SQRT(12), "pct", basis="STDEV(monthly) x sqrt(12)")
    bt.scalar("adj_beta", "Blume-adjusted beta", 0.67 * K(BETA, "raw_beta") + 0.33, "beta", basis="0.67 x raw beta + 0.33")
    bt.blank()
    bt.text("Unlever / relever (Hamada)", "section")
    bt.scalar("beta_tax", "Tax rate", a("tax_rate"), "pct")
    bt.scalar("beta_de_current", "Current market debt / equity", K(WACC, "de_current"), "factor", basis="From WACC sheet")
    bt.scalar("beta_de_target", "Target debt / equity", K(WACC, "de_target"), "factor", basis="From WACC sheet")
    bt.scalar("beta_fallback", "Regression unusable (1 = fewer than 24 observations or beta outside -1..4): use beta of 1.0",
              IF(OR(LT(K(BETA, "n_obs"), 24), LT(K(BETA, "raw_beta"), -1), GT(K(BETA, "raw_beta"), 4)), 1, 0), "int",
              basis="Guards against shells, re-listings and thin trading histories producing absurd betas")
    bt.scalar("beta_levered_input", "Levered beta used (raw or Blume-adjusted per Assumptions; 1.0 if regression unusable)",
              IF(EQ(K(BETA, "beta_fallback"), 1), 1, IF(EQ(a("use_blume"), 1), K(BETA, "adj_beta"), K(BETA, "raw_beta"))), "beta")
    bt.scalar("unlevered_beta", "Unlevered (asset) beta", K(BETA, "beta_levered_input") / (1 + (1 - K(BETA, "beta_tax")) * K(BETA, "beta_de_current")),
              "beta", basis="Levered beta / (1 + (1 - t) x D/E)")
    bt.scalar("selected_beta", "Relevered beta at target structure (used in WACC)",
              K(BETA, "unlevered_beta") * (1 + (1 - K(BETA, "beta_tax")) * K(BETA, "beta_de_target")), "beta",
              basis="Unlevered beta x (1 + (1 - t) x target D/E)", bold=True)
    # data table
    book.set(BETA, data_r0 - 2, 1, "Monthly price data (adjusted close)", "text", "section")
    for c, t in enumerate(["Month end", f"{ds.profile.symbol} close", f"{ip.symbol} close", f"{ds.profile.symbol} return", f"{ip.symbol} return"], start=1):
        book.set(BETA, data_r0 - 1, c, t, "text", "header")
    for i in range(n_px):
        r = data_r0 + i
        book.set(BETA, r, 1, sp.dates[i], "text", "input")
        book.set(BETA, r, 2, float(sp.closes[i]), "price", "input")
        book.set(BETA, r, 3, float(ip.closes[i]), "price", "input")
        if i > 0:
            book.set(BETA, r, 4, CellRef(BETA, r, 2) / CellRef(BETA, r - 1, 2) - 1, "pct2", "formula")
            book.set(BETA, r, 5, CellRef(BETA, r, 3) / CellRef(BETA, r - 1, 3) - 1, "pct2", "formula")
    bt.sh.col_widths = {1: 52, 2: 16, 3: 16, 4: 16, 5: 16}
    bt.sh.freeze = f"A{data_r0}"

    # =====================================================================
    # WACC
    # =====================================================================
    wt = SB(book, WACC, [], labels, dates, nh)
    wt.title("Weighted average cost of capital", f"{ds.profile.name} - CAPM cost of equity, after-tax cost of debt")
    wt.text("Capital structure", "section")
    wt.scalar("w_price", f"Share price ({ccy})", a("price"), "price")
    wt.scalar("w_shares", "Shares outstanding (millions)", a("shares_outstanding"), "num1")
    wt.scalar("market_cap", f"Market capitalisation ({units})", K(WACC, "w_price") * K(WACC, "w_shares"), "num", bold=True)
    wt.scalar("w_debt", f"Total debt ({units}, FY{base_year} book value)", K(BS, "total_debt", L), "num")
    wt.scalar("de_current", "Current debt / equity (market)", IFERROR(K(WACC, "w_debt") / K(WACC, "market_cap"), 0), "factor")
    wt.scalar("dv_current", "Current debt / (debt + equity)", IFERROR(K(WACC, "w_debt") / (K(WACC, "w_debt") + K(WACC, "market_cap")), 0), "pct")
    wt.scalar("dv_target", "Target debt / (debt + equity)", a("target_debt_weight"), "pct")
    wt.scalar("ev_target", "Target equity / (debt + equity)", 1 - K(WACC, "dv_target"), "pct")
    wt.scalar("de_target", "Target debt / equity", IFERROR(K(WACC, "dv_target") / K(WACC, "ev_target"), 0), "factor")
    wt.blank()
    wt.text("Cost of equity (CAPM)", "section")
    wt.scalar("w_rf", "Risk-free rate", a("risk_free"), "pct2")
    wt.scalar("w_beta", "Beta (relevered, from Beta sheet)", K(BETA, "selected_beta"), "beta")
    wt.scalar("w_erp", "Equity risk premium", a("erp"), "pct2")
    wt.scalar("w_size", "Size / specific premium", a("size_premium"), "pct2")
    wt.scalar("cost_of_equity", "Cost of equity", K(WACC, "w_rf") + K(WACC, "w_beta") * K(WACC, "w_erp") + K(WACC, "w_size"), "pct2",
              basis="Rf + beta x ERP + premium", bold=True)
    wt.blank()
    wt.text("Cost of debt", "section")
    wt.scalar("w_kd", "Pre-tax cost of debt", a("cost_of_debt"), "pct2")
    wt.scalar("w_tax", "Tax rate", a("tax_rate"), "pct")
    wt.scalar("kd_after_tax", "After-tax cost of debt", K(WACC, "w_kd") * (1 - K(WACC, "w_tax")), "pct2", basis="Kd x (1 - t)", bold=True)
    wt.blank()
    wt.text("WACC", "section")
    wt.scalar("wacc", "Weighted average cost of capital", K(WACC, "ev_target") * K(WACC, "cost_of_equity") + K(WACC, "dv_target") * K(WACC, "kd_after_tax"),
              "pct2", basis="E/V x Ke + D/V x Kd x (1 - t)", bold=True)
    wt.sh.col_widths = {1: 48, 2: 16, 3: 40}

    # =====================================================================
    # DCF
    # =====================================================================
    dct = SB(book, DCF, [L] + P, labels, dates, nh, first_period=L)
    dct.title("Discounted cash flow valuation (unlevered FCF)", f"{ds.profile.name} - {units}; valuation as of the FY{base_year} balance sheet")
    dct.header("", units)
    dct.section("Free cash flow to the firm")
    dct.row("d_revenue", "Revenue", lambda p: isr("revenue", p), memo=True)
    dct.row("d_ebitda", "EBITDA", lambda p: isr("ebitda", p), memo=True)
    dct.row("d_ebit", "EBIT", lambda p: isr("ebit", p))
    dct.row("d_tax", "Less: taxes on EBIT", lambda p: -K(DCF, "d_ebit", p) * a("tax_rate"), periods=P)
    dct.row("nopat", "NOPAT", lambda p: K(DCF, "d_ebit", p) + K(DCF, "d_tax", p), periods=P, bold=True)
    dct.row("d_da", "Plus: D&A", lambda p: isr("da", p), periods=P)
    dct.row("d_capex", "Less: capital expenditure", lambda p: cfr("capex", p), periods=P)
    dct.row("d_wc", "Less: increase in working capital", lambda p: cfr("change_wc", p), periods=P)
    dct.row("d_other", "Other operating items", lambda p: cfr("other_operating", p), periods=P)
    dct.row("d_sbc", "Plus: SBC add-back (if elected)", lambda p: cfr("sbc", p) * a("sbc_addback"), periods=P)
    dct.row("fcff", "Unlevered free cash flow", lambda p: K(DCF, "nopat", p) + K(DCF, "d_da", p) + K(DCF, "d_capex", p) + K(DCF, "d_wc", p) + K(DCF, "d_other", p) + K(DCF, "d_sbc", p),
            periods=P, bold=True)
    dct.section("Discounting")
    dct.row("year_index", "Year", lambda p: 1.0 if p == P[0] else K(DCF, "year_index", p - 1) + 1, "int", periods=P)
    dct.row("disc_period", "Discount period (years)", lambda p: K(DCF, "year_index", p) - 0.5 * a("mid_year"), "num2", periods=P)
    dct.row("disc_factor", "Discount factor", lambda p: 1 / (1 + K(WACC, "wacc")) ** K(DCF, "disc_period", p), "factor", periods=P)
    dct.row("pv_fcff", "Present value of FCFF", lambda p: K(DCF, "fcff", p) * K(DCF, "disc_factor", p), periods=P, bold=True)
    dct.blank()
    vc = dct.col(L)  # value column for the summary block (column C)
    pN = P[-1]

    def dsc(key: str, label: str, content: Any, fmt: str = "num", bold: bool = False, basis: str = ""):
        return dct.scalar(key, label, content, fmt, basis=basis, bold=bold, col=vc)

    dct.text("Terminal value", "section")
    dsc("sum_pv", "Sum of PV of FCFF", SUM(RangeK(DCF, "pv_fcff", P[0], pN)), bold=True)
    dsc("fcff_terminal", f"Terminal year FCFF ({labels[pN]})", K(DCF, "fcff", pN))
    dsc("ebitda_terminal", f"Terminal year EBITDA ({labels[pN]})", K(DCF, "d_ebitda", pN))
    dsc("d_wacc", "WACC", K(WACC, "wacc"), "pct2")
    dsc("d_g", "Terminal growth", a("terminal_growth"), "pct2")
    dsc("d_mult", "Exit EV / EBITDA multiple", a("exit_multiple"), "mult")
    dsc("tv_gordon", "Terminal value - Gordon growth", K(DCF, "fcff_terminal") * (1 + K(DCF, "d_g")) / (K(DCF, "d_wacc") - K(DCF, "d_g")),
        basis="FCFF x (1 + g) / (WACC - g)")
    dsc("tv_exit", "Terminal value - exit multiple", K(DCF, "ebitda_terminal") * K(DCF, "d_mult"), basis="EBITDA x multiple")
    dsc("tv_disc_period_gordon", "Discount period - Gordon (mid-year adjusted)", K(DCF, "disc_period", pN), "num2")
    dsc("tv_disc_period_exit", "Discount period - exit multiple (end of year)", K(DCF, "year_index", pN), "num2")
    dsc("pv_tv_gordon", "PV of terminal value - Gordon", K(DCF, "tv_gordon") / (1 + K(DCF, "d_wacc")) ** K(DCF, "tv_disc_period_gordon"))
    dsc("pv_tv_exit", "PV of terminal value - exit multiple", K(DCF, "tv_exit") / (1 + K(DCF, "d_wacc")) ** K(DCF, "tv_disc_period_exit"))
    dsc("tv_method", "Selected method (1 = Gordon, 2 = exit multiple)", a("tv_method"), "int")
    dsc("pv_tv", "PV of terminal value (selected)", IF(EQ(K(DCF, "tv_method"), 1), K(DCF, "pv_tv_gordon"), K(DCF, "pv_tv_exit")), bold=True)
    dct.blank()
    dct.text("Equity bridge", "section")
    dsc("enterprise_value", "Enterprise value", K(DCF, "sum_pv") + K(DCF, "pv_tv"), bold=True)
    dsc("less_debt", f"Less: total debt (FY{base_year})", -K(BS, "total_debt", L))
    dsc("plus_cash", f"Plus: cash & short-term investments (FY{base_year})", K(BS, "cash_sti", L))
    dsc("equity_value", "Equity value", K(DCF, "enterprise_value") + K(DCF, "less_debt") + K(DCF, "plus_cash"), bold=True)
    dsc("d_shares", "Shares outstanding (millions)", a("shares_outstanding"), "num1")
    dsc("implied_price", f"Implied value per share ({ccy})", K(DCF, "equity_value") / K(DCF, "d_shares"), "price", bold=True)
    dsc("d_price", f"Current share price ({ccy})", a("price"), "price")
    dsc("upside", "Upside / (downside)", K(DCF, "implied_price") / K(DCF, "d_price") - 1, "pct", bold=True)
    dct.blank()
    dct.text("Implied metrics and cross-checks", "section")
    dsc("tv_share", "Terminal value as % of enterprise value", IFERROR(K(DCF, "pv_tv") / K(DCF, "enterprise_value"), 0), "pct")
    dsc("implied_exit_multiple", "Implied exit multiple from Gordon TV (EV / EBITDA)", IFERROR(K(DCF, "tv_gordon") / K(DCF, "ebitda_terminal"), 0), "mult")
    dsc("implied_growth", "Implied perpetual growth from exit multiple TV",
        IFERROR((K(DCF, "tv_exit") * K(DCF, "d_wacc") - K(DCF, "fcff_terminal")) / (K(DCF, "tv_exit") + K(DCF, "fcff_terminal")), 0), "pct2",
        basis="(TV x WACC - FCFF) / (TV + FCFF)")
    dsc("implied_ev_ebitda_ltm", f"Implied EV / EBITDA (FY{base_year})", IFERROR(K(DCF, "enterprise_value") / K(IS, "ebitda", L), 0), "mult")
    dsc("implied_ev_ebitda_fwd", f"Implied EV / EBITDA ({labels[P[0]]})", IFERROR(K(DCF, "enterprise_value") / K(IS, "ebitda", P[0]), 0), "mult")
    dsc("implied_pe_fwd", f"Implied P / E ({labels[P[0]]})", IFERROR(K(DCF, "implied_price") / K(IS, "eps", P[0]), 0), "mult")
    dsc("market_ev_ebitda", f"Market EV / EBITDA (FY{base_year})", a("ev_ebitda_ltm"), "mult")
    dct.sh.col_widths = {1: 52, 2: 12}
    for p in [L] + P:
        dct.sh.col_widths[dct.col(p)] = 14

    # =====================================================================
    # Sensitivity
    # =====================================================================
    st = SB(book, SENS, [], labels, dates, nh)
    st.title("Sensitivity analysis - implied share price", f"{ds.profile.name} - every cell recomputes the DCF for its WACC / terminal assumption")
    steps = [-0.01, -0.005, 0.0, 0.005, 0.01]
    mult_steps = [-2.0, -1.0, 0.0, 1.0, 2.0]

    def price_gordon(w: Expr, g: Expr) -> Expr:
        pv: Expr = K(DCF, "fcff", P[0]) / (1 + w) ** K(DCF, "disc_period", P[0])
        for p in P[1:]:
            pv = pv + K(DCF, "fcff", p) / (1 + w) ** K(DCF, "disc_period", p)
        tv = K(DCF, "fcff_terminal") * (1 + g) / (w - g) / (1 + w) ** K(DCF, "tv_disc_period_gordon")
        return (pv + tv + K(DCF, "less_debt") + K(DCF, "plus_cash")) / K(DCF, "d_shares")

    def price_exit(w: Expr, m: Expr) -> Expr:
        pv: Expr = K(DCF, "fcff", P[0]) / (1 + w) ** K(DCF, "disc_period", P[0])
        for p in P[1:]:
            pv = pv + K(DCF, "fcff", p) / (1 + w) ** K(DCF, "disc_period", p)
        tv = K(DCF, "ebitda_terminal") * m / (1 + w) ** K(DCF, "tv_disc_period_exit")
        return (pv + tv + K(DCF, "less_debt") + K(DCF, "plus_cash")) / K(DCF, "d_shares")

    def table(title: str, row_label: str, row_key: str, row_steps: List[float], row_fmt: str, row_src: Expr, fn, key_prefix: str):
        st.text(title, "section")
        r0 = st.r
        book.set(SENS, r0, 1, f"{row_label} \\ WACC", "text", "header")
        for j, s in enumerate(steps):
            book.set(SENS, r0, 2 + j, K(WACC, "wacc") + s, "pct2", "header", key=f"{key_prefix}_w{j}")
        for i, rs in enumerate(row_steps):
            r = r0 + 1 + i
            book.set(SENS, r, 1, row_src + rs, row_fmt, "header", key=f"{key_prefix}_r{i}")
            for j in range(len(steps)):
                content = fn(CellRef(SENS, r0, 2 + j), CellRef(SENS, r, 1))
                book.set(SENS, r, 2 + j, IFERROR(content, "n/a"), "price", "formula", key=f"{key_prefix}_{i}_{j}",
                         bold=(i == 2 and j == 2))
        st.r = r0 + len(row_steps) + 2

    table("Gordon growth method: terminal growth vs WACC", "Terminal growth", "g", steps, "pct2", a("terminal_growth"), price_gordon, "sg")
    table("Exit multiple method: EV / EBITDA multiple vs WACC", "Exit multiple", "m", mult_steps, "mult", a("exit_multiple"), price_exit, "sm")
    st.text(f"Base case is the centre cell of each table. Current share price: see Assumptions ({ccy} {ds.market.price:,.2f}).", "note")
    st.sh.col_widths = {1: 30, 2: 14, 3: 14, 4: 14, 5: 14, 6: 14}

    # =====================================================================
    # Ratios
    # =====================================================================
    rt = SB(book, RATIOS, ALL, labels, dates, nh)
    rt.title("Ratio analysis", f"{ds.profile.name}")
    rt.header("", "")

    def R(key, label, fn, fmt="pct", **kw):
        rt.row(key, label, lambda p: IFERROR(fn(p), 0), fmt, **kw)

    rt.section("Growth")
    rt.row("r_rev_growth", "Revenue growth", lambda p: IFERROR(isr("revenue", p) / isr("revenue", p - 1) - 1, 0) if p > 0 else None, "pct")
    rt.row("r_ebitda_growth", "EBITDA growth", lambda p: IFERROR(isr("ebitda", p) / isr("ebitda", p - 1) - 1, 0) if p > 0 else None, "pct")
    rt.row("r_ni_growth", "Net income growth", lambda p: IFERROR(isr("net_income", p) / isr("net_income", p - 1) - 1, 0) if p > 0 else None, "pct")
    rt.row("r_eps_growth", "Diluted EPS growth", lambda p: IFERROR(isr("eps", p) / isr("eps", p - 1) - 1, 0) if p > 0 else None, "pct")
    rt.section("Profitability")
    R("r_gross_margin", "Gross margin", lambda p: isr("gross_profit", p) / isr("revenue", p))
    R("r_ebitda_margin", "EBITDA margin", lambda p: isr("ebitda", p) / isr("revenue", p))
    R("r_ebit_margin", "EBIT margin", lambda p: isr("ebit", p) / isr("revenue", p))
    R("r_net_margin", "Net margin", lambda p: isr("net_income", p) / isr("revenue", p))
    R("r_roe", "Return on equity (ending equity)", lambda p: isr("net_income", p) / bsr("total_equity", p))
    R("r_roa", "Return on assets", lambda p: isr("net_income", p) / bsr("total_assets", p))
    R("r_roic", "Return on invested capital (NOPAT / (debt + equity - cash))",
      lambda p: isr("ebit", p) * (1 - a("tax_rate")) / (bsr("total_debt", p) + bsr("total_equity", p) - bsr("cash_sti", p)))
    rt.section("Cash flow")
    R("r_fcf_margin", "FCF margin", lambda p: cfr("fcf", p) / isr("revenue", p))
    R("r_fcf_conversion", "FCF conversion (FCF / net income)", lambda p: cfr("fcf", p) / isr("net_income", p))
    R("r_capex_rev", "Capex % of revenue", lambda p: -cfr("capex", p) / isr("revenue", p))
    R("r_capex_da", "Capex / D&A", lambda p: -cfr("capex", p) / isr("da", p), "mult")
    rt.section("Liquidity and leverage")
    R("r_current", "Current ratio", lambda p: bsr("total_current_assets", p) / bsr("total_current_liabilities", p), "mult")
    R("r_quick", "Quick ratio", lambda p: (bsr("cash_sti", p) + bsr("receivables", p)) / bsr("total_current_liabilities", p), "mult")
    R("r_de", "Debt / equity", lambda p: bsr("total_debt", p) / bsr("total_equity", p), "mult")
    R("r_nd_ebitda", "Net debt / EBITDA", lambda p: bsr("net_debt", p) / isr("ebitda", p), "mult")
    R("r_int_cov", "Interest coverage (EBIT / interest)", lambda p: isr("ebit", p) / isr("interest_expense", p), "mult")
    R("r_asset_turn", "Asset turnover", lambda p: isr("revenue", p) / bsr("total_assets", p), "mult")
    rt.section("Working capital")
    R("r_dso", "Days sales outstanding", lambda p: bsr("receivables", p) / isr("revenue", p) * 365, "days")
    R("r_dio", "Days inventory outstanding", lambda p: bsr("inventory", p) / isr("cogs", p) * 365, "days")
    R("r_dpo", "Days payables outstanding", lambda p: bsr("payables", p) / isr("cogs", p) * 365, "days")
    rt.section("Per share")
    R("r_eps", f"Diluted EPS ({ccy})", lambda p: isr("eps", p), "price")
    R("r_dps", f"Dividends per share ({ccy})", lambda p: -cfr("dividends", p) / isr("diluted_shares", p), "price")
    R("r_bvps", f"Book value per share ({ccy})", lambda p: bsr("total_equity", p) / isr("diluted_shares", p), "price")
    R("r_fcfps", f"FCF per share ({ccy})", lambda p: cfr("fcf", p) / isr("diluted_shares", p), "price")
    rt.sh.col_widths = {1: 52, 2: 10}

    # =====================================================================
    # Feedback (quantitative checks are formulas; narrative is text)
    # =====================================================================
    fb = SB(book, FEED, [], labels, dates, nh)
    fb.title("Model feedback", f"{ds.profile.name} - quantitative integrity checks and qualitative assessment")
    fb.text("Quantitative checks (live formulas)", "section")
    hdr_r = fb.r
    for c, t in enumerate(["Check", "Value", "Threshold", "Status", "Why it matters"], start=1):
        book.set(FEED, hdr_r, c, t, "text", "header")
    fb.r += 1
    check_keys: List[str] = []

    def check(key: str, label: str, value: Expr, fmt: str, threshold: str, cond: Expr, why: str, fail_word: str = "FLAG"):
        r = fb.r
        book.set(FEED, r, 1, label, "text", "label", indent=1)
        book.set(FEED, r, 2, value, fmt, "formula", key=key)
        book.set(FEED, r, 3, threshold, "text", "note")
        book.set(FEED, r, 4, IF(cond, "PASS", fail_word), "text", "check", key=key + "_status")
        book.set(FEED, r, 5, why, "text", "note")
        check_keys.append(key + "_status")
        fb.r += 1

    bs_abs = ABS(K(BS, "balance_check", ALL[0]))
    for p in ALL[1:]:
        bs_abs = MAX(bs_abs, ABS(K(BS, "balance_check", p)))
    check("chk_balance", "Balance sheet balances (max |A - L - E|, all years)", bs_abs, "num2", "< 0.5", LT(bs_abs, 0.5),
          "A non-zero difference means the three statements are not linked correctly.", "FAIL")
    cf_abs = ABS(K(CF, "cash_check", P[0]))
    for p in P[1:]:
        cf_abs = MAX(cf_abs, ABS(K(CF, "cash_check", p)))
    check("chk_cash", "Projected ending cash equals balance sheet cash (max diff)", cf_abs, "num2", "< 0.5", LT(cf_abs, 0.5),
          "The cash flow statement must drive the balance sheet cash line.", "FAIL")
    check("chk_ebit_rec", f"Historical EBIT reconciles to reported (FY{base_year} diff)", K(IS, "ebit", L) - K(HIST, "operating_income", L), "num2",
          "= 0", LT(ABS(K(IS, "ebit", L) - K(HIST, "operating_income", L)), 0.5), "Reconciling items are captured in other operating expenses.", "FAIL")
    check("chk_ni_rec", f"Historical net income reconciles to reported (FY{base_year} diff)", K(IS, "net_income", L) - K(HIST, "net_income", L), "num2",
          "= 0", LT(ABS(K(IS, "net_income", L) - K(HIST, "net_income", L)), 0.5), "Minority interest and discontinued items are captured separately.", "FAIL")
    check("chk_beta", "Beta cross-check (slope - covariance/variance)", K(BETA, "raw_beta") - K(BETA, "beta_check"), "factor", "= 0",
          LT(ABS(K(BETA, "raw_beta") - K(BETA, "beta_check")), 1e-6), "Two independent formulas must agree.", "FAIL")
    check("chk_g_rf", "Terminal growth <= risk-free rate", a("terminal_growth"), "pct2", "<= risk-free", LE(a("terminal_growth"), a("risk_free")),
          "A perpetual growth rate above the risk-free rate implies the company outgrows the economy forever.")
    check("chk_spread", "WACC - terminal growth spread", K(WACC, "wacc") - a("terminal_growth"), "pct2", ">= 2.0%",
          GE(K(WACC, "wacc") - a("terminal_growth"), 0.02), "A thin spread makes the Gordon terminal value explode and unreliable.")
    check("chk_tv_share", "Terminal value share of enterprise value", K(DCF, "tv_share"), "pct", "<= 75%", LE(K(DCF, "tv_share"), 0.75),
          "When most value sits in the terminal period the valuation is highly sensitive to WACC and g.")
    check("chk_implied_mult", "Implied exit multiple from Gordon TV", K(DCF, "implied_exit_multiple"), "mult", "5x - 25x",
          AND(GE(K(DCF, "implied_exit_multiple"), 5), LE(K(DCF, "implied_exit_multiple"), 25)),
          "Cross-checks the perpetuity assumption against how businesses actually trade.")
    # only exponentiate positive ratios: a negative base with a fractional power is #NUM! in Excel but a real
    # odd root in LibreOffice, so guarding keeps every engine identical when revenue turns negative
    hist_cagr = IF(AND(GT(K(IS, "revenue", L), 0), GT(K(IS, "revenue", 0), 0)),
                   (K(IS, "revenue", L) / K(IS, "revenue", 0)) ** (1 / max(L, 1)) - 1, 0)
    proj_cagr = IF(AND(GT(K(IS, "revenue", pN), 0), GT(K(IS, "revenue", L), 0)),
                   (K(IS, "revenue", pN) / K(IS, "revenue", L)) ** (1 / N) - 1, 0)
    check("chk_growth", "Projected revenue CAGR minus historical CAGR", proj_cagr - hist_cagr, "pct", "<= +5.0pp",
          LE(proj_cagr - hist_cagr, 0.05), "Forecasting acceleration well above the track record needs a clear justification.")
    check("chk_margin", "EBITDA margin expansion (terminal year vs base year)", K(IS, "m_ebitda_margin", pN) - K(IS, "m_ebitda_margin", L), "pct",
          "<= +5.0pp", LE(K(IS, "m_ebitda_margin", pN) - K(IS, "m_ebitda_margin", L), 0.05),
          "Margins tend to mean-revert; large expansion should be evidenced.")
    ppe_min = K(BS, "ppe", P[0])
    for p in P[1:]:
        ppe_min = MIN(ppe_min, K(BS, "ppe", p))
    check("chk_ppe", "Minimum projected net PP&E", ppe_min, "num", "> 0", GT(ppe_min, 0),
          "Negative PP&E means D&A exceeds capex for too long - check the capex assumption.")
    check("chk_capex_da", "Terminal year capex / D&A", IFERROR(-K(CF, "capex", pN) / K(IS, "da", pN), 0), "mult", ">= 1.0x",
          GE(IFERROR(-K(CF, "capex", pN) / K(IS, "da", pN), 0), 1.0), "A growing company must reinvest at least its depreciation in steady state.")
    check("chk_int_cov", "Terminal year interest coverage (EBIT / interest)", IFERROR(K(IS, "ebit", pN) / K(IS, "interest_expense", pN), 99), "mult",
          ">= 3.0x", GE(IFERROR(K(IS, "ebit", pN) / K(IS, "interest_expense", pN), 99), 3), "Weak coverage signals credit risk not captured in the cost of debt.")
    check("chk_leverage", f"Net debt / EBITDA (FY{base_year})", K(RATIOS, "r_nd_ebitda", L), "mult", "<= 3.5x", LE(K(RATIOS, "r_nd_ebitda", L), 3.5),
          "High leverage should be reflected in the cost of debt and target capital structure.")
    check("chk_r2", "Beta regression R-squared", K(BETA, "r_squared"), "factor", ">= 0.10", GE(K(BETA, "r_squared"), 0.10),
          "A low R-squared means the index explains little of the stock's moves; consider a peer/industry beta.")
    check("chk_beta_usable", "Regression beta usable (fallback to 1.0 not triggered)", K(BETA, "raw_beta"), "beta", "-1 to 4, n >= 24",
          EQ(K(BETA, "beta_fallback"), 0), "An extreme regression beta usually reflects a re-listing, a shell company or thin trading; the model then uses a market beta of 1.0.")
    check("chk_nobs", "Beta regression observations", K(BETA, "n_obs"), "int", ">= 36", GE(K(BETA, "n_obs"), 36),
          "Fewer than three years of monthly returns gives an unstable beta.")
    check("chk_upside", "Implied upside / (downside) vs market price", K(DCF, "upside"), "pct", "within +/-50%",
          LE(ABS(K(DCF, "upside")), 0.5), "A very large gap to the market usually means an assumption, not the market, is wrong.")
    check("chk_equity_positive", "Implied equity value per share", K(DCF, "implied_price"), "price", "> 0",
          GT(K(DCF, "implied_price"), 0), "A non-positive value means projected cash flows do not cover net debt; a mechanical DCF is not meaningful for turnaround or loss-making cases.")
    mcap_ratio = IFERROR(K(WACC, "market_cap") / K(BS, "total_equity", L), 0)
    check("chk_mcap_book", f"Market cap / book equity (FY{base_year})", mcap_ratio, "mult", "0.02x - 1,000x or negative equity",
          OR(LE(K(BS, "total_equity", L), 0), AND(GE(mcap_ratio, 0.02), LE(mcap_ratio, 1000))),
          "A ratio far outside this band usually means the quoted price and the share count refer to different share classes "
          "(e.g. Berkshire A vs B shares) or units - check 'Shares outstanding' in Assumptions.")
    check("chk_wacc_range", "WACC", K(WACC, "wacc"), "pct2", "6% - 14%", AND(GE(K(WACC, "wacc"), 0.06), LE(K(WACC, "wacc"), 0.14)),
          "Discount rates outside this band are unusual for listed companies and worth a second look.")
    fb.blank()
    n_fail: Expr = IF(EQ(K(FEED, check_keys[0]), "FAIL"), 1, 0)
    n_flag: Expr = IF(EQ(K(FEED, check_keys[0]), "FLAG"), 1, 0)
    for ck in check_keys[1:]:
        n_fail = n_fail + IF(EQ(K(FEED, ck), "FAIL"), 1, 0)
        n_flag = n_flag + IF(EQ(K(FEED, ck), "FLAG"), 1, 0)
    fb.scalar("n_fail", "Integrity failures", n_fail, "int", bold=True)
    fb.scalar("n_flag", "Assumption flags", n_flag, "int", bold=True)
    fb.scalar("overall_status", "Overall status",
              IF(GT(K(FEED, "n_fail"), 0), "FAIL - model integrity broken",
                 IF(GT(K(FEED, "n_flag"), 0), "REVIEW - assumptions flagged", "PASS - all checks clear")), "text", bold=True)
    fb.blank()
    fb.text("Credit and quality scores", "section")
    ta = K(BS, "total_assets", L)
    fb.scalar("z_a", "A: Working capital / total assets", IFERROR((K(BS, "total_current_assets", L) - K(BS, "total_current_liabilities", L)) / ta, 0), "factor")
    fb.scalar("z_b", "B: Retained earnings / total assets", IFERROR(K(HIST, "retained_earnings", L) / ta, 0), "factor")
    fb.scalar("z_c", "C: EBIT / total assets", IFERROR(K(IS, "ebit", L) / ta, 0), "factor")
    fb.scalar("z_d", "D: Market cap / total liabilities", IFERROR(K(WACC, "market_cap") / K(BS, "total_liabilities", L), 0), "factor")
    fb.scalar("z_e", "E: Revenue / total assets", IFERROR(K(IS, "revenue", L) / ta, 0), "factor")
    fb.scalar("altman_z", "Altman Z-score (1.2A + 1.4B + 3.3C + 0.6D + 1.0E)",
              1.2 * K(FEED, "z_a") + 1.4 * K(FEED, "z_b") + 3.3 * K(FEED, "z_c") + 0.6 * K(FEED, "z_d") + 1.0 * K(FEED, "z_e"), "num2", bold=True)
    fb.scalar("altman_zone", "Altman zone", IF(GT(K(FEED, "altman_z"), 2.99), "Safe", IF(LT(K(FEED, "altman_z"), 1.81), "Distress", "Grey")), "text", bold=True)
    if nh >= 2:
        Lp = L - 1
        f_items = [
            ("f1", "ROA > 0", GT(K(IS, "net_income", L), 0)),
            ("f2", "Operating cash flow > 0", GT(K(CF, "cfo", L), 0)),
            ("f3", "ROA improved vs prior year", GT(K(RATIOS, "r_roa", L), K(RATIOS, "r_roa", Lp))),
            ("f4", "Cash flow from operations > net income (accruals)", GT(K(CF, "cfo", L), K(IS, "net_income", L))),
            ("f5", "Leverage (LT debt / assets) decreased", LT(IFERROR(K(BS, "long_term_debt", L) / K(BS, "total_assets", L), 0),
                                                                IFERROR(K(BS, "long_term_debt", Lp) / K(BS, "total_assets", Lp), 0))),
            ("f6", "Current ratio improved", GT(K(RATIOS, "r_current", L), K(RATIOS, "r_current", Lp))),
            ("f7", "No net share issuance", LE(K(IS, "diluted_shares", L), K(IS, "diluted_shares", Lp))),
            ("f8", "Gross margin improved", GT(K(RATIOS, "r_gross_margin", L), K(RATIOS, "r_gross_margin", Lp))),
            ("f9", "Asset turnover improved", GT(K(RATIOS, "r_asset_turn", L), K(RATIOS, "r_asset_turn", Lp))),
        ]
        total: Optional[Expr] = None
        for key, lab, cond in f_items:
            fb.scalar(key, f"Piotroski: {lab}", IF(cond, 1, 0), "int")
            total = K(FEED, key) if total is None else total + K(FEED, key)
        fb.scalar("piotroski", f"Piotroski F-score (FY{base_year} vs FY{base_year - 1}, 0-9)", total, "int", bold=True)
    fb.sh.col_widths = {1: 62, 2: 16, 3: 16, 4: 30, 5: 90}
    narrative_start = fb.r + 1

    # ---- evaluate everything before writing the narrative ---------------
    errors = book.evaluate_all()
    from .feedback import build_feedback  # local import to avoid a cycle
    feedback = build_feedback(book, ds, A, L, P)
    fb.r = narrative_start
    fb.text("Qualitative assessment", "section")
    for sec in feedback["qualitative"]:
        fb.text(sec["title"], "subtitle", bold=True)
        for line in sec["points"]:
            fb.text("- " + line, "text", wrap=True, merge_to=5)
        fb.blank()
    fb.text("Methodology", "section")
    for line in feedback["methodology"]:
        fb.text("- " + line, "text", wrap=True, merge_to=5)

    summary = {
        "company": ds.profile.name, "symbol": ds.profile.symbol, "currency": ccy, "units": units,
        "price": ds.market.price, "price_date": ds.market.price_date,
        "implied_price": book.num(DCF, "implied_price"), "upside": book.num(DCF, "upside"),
        "enterprise_value": book.num(DCF, "enterprise_value"), "equity_value": book.num(DCF, "equity_value"),
        "wacc": book.num(WACC, "wacc"), "cost_of_equity": book.num(WACC, "cost_of_equity"),
        "raw_beta": book.num(BETA, "raw_beta"), "selected_beta": book.num(BETA, "selected_beta"),
        "r_squared": book.num(BETA, "r_squared"), "terminal_growth": A.values["terminal_growth"],
        "tv_share": book.num(DCF, "tv_share"), "overall_status": book.val(FEED, "overall_status"),
        "n_fail": book.num(FEED, "n_fail"), "n_flag": book.num(FEED, "n_flag"),
        "altman_z": book.num(FEED, "altman_z"), "piotroski": book.num(FEED, "piotroski") if nh >= 2 else None,
        "base_year": base_year, "labels": labels, "error_cells": {k: v for k, v in errors.items() if v},
        "revenue_base": book.num(IS, "revenue", L), "revenue_terminal": book.num(IS, "revenue", pN),
        "ebitda_margin_base": book.num(IS, "m_ebitda_margin", L), "ebitda_margin_terminal": book.num(IS, "m_ebitda_margin", pN),
        "source": ds.source, "retrieved_at": ds.retrieved_at, "index": ds.index_prices.name,
    }
    return ModelResult(book=book, dataset=ds, assumptions=A, summary=summary, feedback=feedback)
