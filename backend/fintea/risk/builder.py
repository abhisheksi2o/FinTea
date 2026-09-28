"""Build the default-risk workbook as a formula-driven Book.

Sheet order: Cover, Assessment, Dashboard, Inputs, Financials, Ratios, Altman Z,
Piotroski F, Beneish M, Distress Models, Merton PD, Synthetic Rating, Data Quality.

Every score, probability and ratio is an Excel formula that traces back to the
blue input cells: reported statements (Financials), market data and model choices
(Inputs) and the published coefficients (Inputs). The only Python-computed numbers
are the iterated Merton asset value and volatility, which the workbook re-checks
with its own formulas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..model.builder import M, SB
from ..providers.base import FIELD_LABELS, FinancialDataset
from ..sheet import (ABS, AND, COUNT, EQ, EXP, GE, GT, IF, IFERROR, LE, LN, LOG10, LT, MAX, MIN, NORMSDIST, OR, SQRT, STDEV,
                     Book, CellRef, Chart, ChartSeries, Expr, K, RangeRef)
from ..sheet.expr import lift
from . import spec as S
from .inputs import RISK_INPUT_SPECS, RiskInputs, derive_inputs
from .merton import solve_merton
from .periods import analysis_periods

COVER, ASSESS, DASH, INP, FIN, RAT, DUP, ALT, PIO, BEN, DIST, MER, RTG, DQ = (
    "Cover", "Assessment", "Dashboard", "Inputs", "Financials", "Ratios", "DuPont", "Altman Z", "Piotroski F", "Beneish M",
    "Distress Models", "Merton PD", "Synthetic Rating", "Data Quality")
SHEET_ORDER = [COVER, ASSESS, DASH, INP, FIN, RAT, DUP, ALT, PIO, BEN, DIST, MER, RTG, DQ]
NAVY, BLUE, ORANGE, PURPLE, GREEN, GOLD, RED, GREY = "1F3864", "2E75B6", "C55A11", "7030A0", "548235", "BF8F00", "C00000", "7F7F7F"
TAB_COLORS = {COVER: NAVY, ASSESS: NAVY, DASH: RED, INP: BLUE, FIN: GREY, RAT: PURPLE, DUP: PURPLE, ALT: GREEN, PIO: GREEN, BEN: GOLD,
              DIST: GREEN, MER: ORANGE, RTG: ORANGE, DQ: GREY}

FIN_GROUPS = [
    ("Income statement", ["revenue", "cogs", "gross_profit", "sga", "operating_income", "da", "ebitda", "interest_expense",
                          "interest_income", "pretax_income", "tax", "net_income"]),
    ("Share data", ["diluted_shares", "shares_outstanding"]),
    ("Balance sheet", ["cash", "cash_and_sti", "receivables", "inventory", "current_assets", "ppe", "goodwill_intangibles",
                       "total_assets", "payables", "short_term_debt", "current_liabilities", "long_term_debt",
                       "total_liabilities", "total_equity", "stockholders_equity", "retained_earnings", "total_debt"]),
    ("Cash flow statement", ["cfo", "capex", "cfi", "cff", "dividends", "buybacks", "stock_issued", "debt_issued", "debt_repaid",
                             "begin_cash", "net_change_cash", "end_cash", "free_cash_flow"]),
]
MODEL_INPUTS = [
    ("Altman Z / Z' / Z''", ["current_assets", "current_liabilities", "retained_earnings", "operating_income", "total_liabilities", "total_equity", "revenue"], False, True),
    ("Piotroski F", ["net_income", "cfo", "total_debt", "current_assets", "current_liabilities", "cogs", "revenue"], True, True),
    ("Beneish M", ["receivables", "revenue", "cogs", "current_assets", "ppe", "da", "sga", "long_term_debt", "current_liabilities", "cfo"], True, True),
    ("Ohlson O", ["total_liabilities", "current_assets", "current_liabilities", "net_income", "da"], True, True),
    ("Zmijewski X", ["net_income", "total_liabilities", "current_assets", "current_liabilities"], False, True),
    ("Springate S", ["current_assets", "current_liabilities", "operating_income", "pretax_income", "revenue"], False, True),
    ("Grover G", ["current_assets", "current_liabilities", "operating_income", "net_income"], False, True),
    ("Taffler Z", ["pretax_income", "current_liabilities", "current_assets", "total_liabilities", "inventory", "da", "revenue"], False, True),
    ("Merton distance to default", ["short_term_debt", "long_term_debt"], False, False),
    ("Synthetic rating (interest coverage)", ["operating_income", "interest_expense"], False, True),
]
RATING_CLASSES = [("AAA", ["AAA"]), ("AA", ["AA+", "AA", "AA-"]), ("A", ["A+", "A", "A-"]), ("BBB", ["BBB+", "BBB", "BBB-"]),
                  ("BB", ["BB+", "BB", "BB-"]), ("B", ["B+", "B", "B-"]), ("CCC", ["CCC+", "CCC", "CCC-", "CC", "C"])]


@dataclass
class RiskResult:
    book: Book
    dataset: FinancialDataset
    inputs: RiskInputs
    summary: Dict[str, Any]
    feedback: Dict[str, Any]
    merton: Optional[Dict[str, Any]]


def _fy_end_prices(ds: FinancialDataset, periods: List[Any], L: int) -> List[Optional[float]]:
    """Month-end close nearest each period end, in the reporting currency; None for the latest period (current price)."""
    ms = ds.stock_prices
    factor = 1.0
    if ds.market.listing_price and ds.market.listing_price > 0:
        factor = ds.market.price / ds.market.listing_price   # minor-unit and FX conversion the provider applied to the price
    out: List[Optional[float]] = []
    for i, per in enumerate(periods):
        if i == L:
            out.append(None)
            continue
        target = per.period_end[:7]
        best = None
        for d, c in zip(ms.dates, ms.closes):
            if d[:7] <= target:
                best = c
        if best is None:
            best = ms.closes[0] if ms.closes else ds.market.listing_price or ds.market.price
        out.append(float(best) * factor)
    return out


def _months_between(a: str, b: str) -> int:
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def _days_between(a: str, b: str) -> int:
    try:
        return abs((datetime.strptime(b[:10], "%Y-%m-%d") - datetime.strptime(a[:10], "%Y-%m-%d")).days)
    except ValueError:
        return 0


def build_risk_model(ds: FinancialDataset, inputs: Optional[RiskInputs] = None,
                     overrides: Optional[Dict[str, Any]] = None, basis: str = "ltm") -> RiskResult:
    """basis: "ltm" (default) adds a latest-twelve-months column from the quarterly statements when the provider supplied
    one that is newer than the last fiscal year; "annual" analyses the reported fiscal years only."""
    if inputs is not None:
        basis = str(inputs.stats.get("basis") or basis)   # the inputs were derived on a basis; the book must match it
    A = analysis_periods(ds, basis)
    P = A.periods
    R = inputs or derive_inputs(ds, overrides, basis)
    nh = len(P)
    H = list(range(nh))
    L = nh - 1
    P1 = H[1:]                                   # periods with a prior year
    has_prior = nh >= 2                          # Piotroski, Beneish and Ohlson need year-over-year changes
    labels = list(A.labels)
    dates = A.dates
    name, sym, ccy = ds.profile.name, ds.profile.symbol, ds.profile.currency
    units = f"{ccy} millions"
    base_year = P[L].fiscal_year
    base_label = A.base_label
    financial = S.is_financial(ds.profile.sector, ds.profile.industry)
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    book = Book()
    book.meta = {"company": name, "symbol": sym, "currency": ccy, "units": units, "labels": labels, "dates": dates,
                 "nh": nh, "np": 0, "source": ds.source, "generated": generated, "kind": "risk",
                 "basis": A.basis, "ltm": A.ltm, "base_label": base_label, "balance_date": A.balance_date,
                 "periods_note": A.describe(), "basis_note": A.note,
                 "title": f"{name} default risk analysis",
                 "defined_names": {"CompositeRiskScore": (DASH, "composite_score"), "NaiveDefaultProbability": (MER, "pd_naive"),
                                   "SyntheticRating": (RTG, "rating"), "MarketCap": (INP, "market_cap"), "AltmanZ2": (DASH, "sig_z2_value")}}
    for s in SHEET_ORDER:
        book.sheet(s)

    def inp(k: str) -> K: return K(INP, k)
    def fin(k: str, p: int) -> K: return K(FIN, k, p)
    def rat(k: str, p: int) -> K: return K(RAT, k, p)
    def dup(k: str, p: int) -> K: return K(DUP, k, p)
    def alt(k: str, p: int) -> K: return K(ALT, k, p)
    def pio(k: str, p: int) -> K: return K(PIO, k, p)
    def ben(k: str, p: int) -> K: return K(BEN, k, p)
    def dis(k: str, p: int) -> K: return K(DIST, k, p)
    def mer(k: str) -> K: return K(MER, k)
    def rtg(k: str) -> K: return K(RTG, k)
    def dsh(k: str) -> K: return K(DASH, k)
    def safe(e: Expr) -> Expr: return IFERROR(e, 0)
    NA_TEXT = "n/a (needs a prior year)"
    def prior(sheet: str, k: str, p: int) -> Expr:
        """Reference to a year-over-year model output, or an 'n/a' text when only one fiscal year is available."""
        return K(sheet, k, p) if has_prior else lift(NA_TEXT)

    def hdr(sheet: str, sb: SB, cols: List[str]) -> None:
        for c, t in enumerate(cols, start=1):
            book.set(sheet, sb.r, c, t, "text", "header")
        sb.r += 1

    def lookup_desc(value: Expr, n: int, lb_key: Callable[[int], str], val_key: Callable[[int], str]) -> Expr:
        """Nested IF over a table sorted by descending lower bound; the last row is the catch-all."""
        e: Expr = K(INP, val_key(n - 1))
        for i in reversed(range(n - 1)):
            e = IF(GE(value, K(INP, lb_key(i))), K(INP, val_key(i)), e)
        return e

    def lookup_eq(value: Expr, n: int, match_key: Callable[[int], str], val_key: Callable[[int], str], default: Any) -> Expr:
        e: Expr = lift(default)
        for i in reversed(range(n)):
            e = IF(EQ(value, K(INP, match_key(i))), K(INP, val_key(i)), e)
        return e

    # =====================================================================
    # Inputs
    # =====================================================================
    ib = SB(book, INP, [], labels, dates, nh)
    ib.title("Inputs and model parameters", f"{name} ({sym}) - blue cells are inputs; every score formula in this workbook references these cells")
    ib.text("Company and market inputs", "section")
    hdr(INP, ib, ["Input", "Value", "Basis / derivation"])
    cur_sec = None
    for s in RISK_INPUT_SPECS:
        if s.section != cur_sec:
            cur_sec = s.section
            book.set(INP, ib.r, 1, s.section, "text", "subtitle", bold=True)
            ib.r += 1
        ib.scalar(s.key, s.label, R.values[s.key], s.fmt, basis=R.basis.get(s.key, ""), style="input")
    ib.blank()
    ib.text("Derived market metrics", "section")
    ib.scalar("market_cap", f"Market capitalisation ({units})", inp("price") * inp("shares_outstanding"), "num", basis="Share price x shares outstanding")
    ib.scalar("market_cap_usd_bn", "Market capitalisation (USD billions)", inp("market_cap") * inp("fx_to_usd") / 1000, "num2", basis="Market cap x FX to USD / 1,000")
    ib.scalar("is_large", "Large-firm rating table in use (1 = yes)",
              IF(EQ(inp("rating_table"), 1), IF(GT(inp("market_cap_usd_bn"), inp("large_firm_threshold")), 1, 0), IF(EQ(inp("rating_table"), 2), 1, 0)),
              "int", basis="Automatic by market capitalisation unless a table is forced")
    wsum: Expr = inp(S.COMPOSITE_SIGNALS[0].key)
    for sg in S.COMPOSITE_SIGNALS[1:]:
        wsum = wsum + inp(sg.key)
    ib.scalar("weight_total", "Sum of composite weights", wsum, "pct", basis="Must equal 100% (checked on the Data Quality sheet)")
    ib.blank()
    ib.text("Model coefficients and thresholds (as published; blue so they can be audited or changed)", "section")
    hdr(INP, ib, ["Coefficient / threshold", "Value", "Applies to", "Source"])
    for m in S.ALL_MODELS:
        book.set(INP, ib.r, 1, m.name, "text", "subtitle", bold=True)
        book.set(INP, ib.r, 3, m.description, "text", "note")
        ib.r += 1
        for c in m.coefs:
            fmt = "int" if c.key == "c_dd_trading_days" else "factor"
            book.set(INP, ib.r, 1, c.label, "text", "label", indent=1)
            book.set(INP, ib.r, 2, c.value, fmt, "input", key=c.key)
            book.set(INP, ib.r, 3, c.variable, "text", "note")
            book.set(INP, ib.r, 4, m.source, "text", "note")
            ib.r += 1
        for t in m.thresholds:
            fmt = "int" if t.key.startswith("t_f_") else ("pct" if t.key in ("t_o_pd", "t_x_pd") else "score")
            book.set(INP, ib.r, 1, t.label, "text", "label", indent=1)
            book.set(INP, ib.r, 2, t.value, fmt, "input", key=t.key)
            book.set(INP, ib.r, 3, "threshold", "text", "note")
            book.set(INP, ib.r, 4, m.source, "text", "note")
            ib.r += 1
    ib.blank()
    ib.text("Rating tables", "section")

    def table(title: str, columns: List[str], rows: List[List[Any]], keyfn: Callable[[int, int], Optional[str]],
              fmts: List[str], source: str) -> None:
        book.set(INP, ib.r, 1, title, "text", "subtitle", bold=True)
        book.set(INP, ib.r, 4, source, "text", "note")
        ib.r += 1
        hdr(INP, ib, columns)
        for i, row in enumerate(rows):
            for c, (v, f) in enumerate(zip(row, fmts), start=1):
                book.set(INP, ib.r, c, v, f, "input", key=keyfn(i, c))
            ib.r += 1
        ib.blank()

    dl = [[lb if lb != float("-inf") else -99.0, r, sp] for lb, r, sp in S.DAMODARAN_LARGE]
    table(f"Interest coverage -> rating -> default spread, large firms (market cap > USD {S.LARGE_FIRM_MCAP_USD_BN:.0f}bn); last row is the catch-all",
          ["Coverage at least", "Rating", "Default spread"], dl, lambda i, c: {1: f"rt_l_lb_{i}", 2: f"rt_l_r_{i}", 3: f"rt_l_s_{i}"}[c],
          ["num2", "text", "pct2"], S.DAMODARAN_SOURCE)
    dsm = [[lb if lb != float("-inf") else -99.0, r, sp] for lb, r, sp in S.DAMODARAN_SMALL]
    table("Interest coverage -> rating -> default spread, smaller / riskier firms; last row is the catch-all",
          ["Coverage at least", "Rating", "Default spread"], dsm, lambda i, c: {1: f"rt_s_lb_{i}", 2: f"rt_s_r_{i}", 3: f"rt_s_s_{i}"}[c],
          ["num2", "text", "pct2"], S.DAMODARAN_SOURCE)
    em_rows = [[lb if lb != float("-inf") else -99.0, r] for lb, r in S.EM_RATING_TABLE]
    table("Altman EM score -> US bond rating equivalent; last row is the catch-all", ["EM score at least", "Rating"], em_rows,
          lambda i, c: {1: f"em_lb_{i}", 2: f"em_r_{i}"}[c], ["num2", "text"], S.ALTMAN_Z2.source)
    sp_rows = [[r, S.SPREAD_BY_RATING[r]] for r in S.RATING_ORDER]
    table("Default spread by rating notch (Damodaran; notches without a published spread are interpolated)", ["Rating", "Default spread"],
          sp_rows, lambda i, c: {1: f"sp_r_{i}", 2: f"sp_s_{i}"}[c], ["text", "pct2"], S.DAMODARAN_SOURCE)
    dr_classes = list(S.SP_DEFAULT_RATES)
    dr_rows = [[cls] + [S.SP_DEFAULT_RATES[cls][h] for h in S.SP_HORIZONS] for cls in dr_classes]
    table(f"Average cumulative default rates by rating class ({S.SP_AS_OF})", ["Rating class", "1 year", "5 years"],
          dr_rows, lambda i, c: {1: f"dr_cls_{i}", 2: f"dr_{dr_classes[i]}_1", 3: f"dr_{dr_classes[i]}_5"}[c],
          ["text", "pct2", "pct2"], S.SP_SOURCE)
    ib.sh.col_widths = {1: 62, 2: 14, 3: 60, 4: 90, 5: 12}

    # =====================================================================
    # Financials (reported inputs)
    # =====================================================================
    fs = SB(book, FIN, H, labels, dates, nh)
    fs.title("Financial statements (as reported)", f"{name} - {units}; source: {ds.source}")
    fs.header("Reported line item", "Source field")

    def raw(key: str, scale: float = M):
        return lambda p: (P[p].fields.get(key) or 0.0) / scale

    for title, keys in FIN_GROUPS:
        fs.section(title)
        for k in keys:
            fmt = "num1" if "shares" in k else "num"
            fs.row(k, FIELD_LABELS[k], raw(k), fmt, style="input", note=P[L].source_fields.get(k, ""))
    fs.section("Market data by period")
    fy_px = _fy_end_prices(ds, P, L)
    fs.row("fy_price", f"Share price ({ccy}; period-end month close, latest column = current price)",
           lambda p: inp("price") if p == L else fy_px[p], "price", note="Monthly price series; latest year links to Inputs")
    fs.row("mve", f"Market value of equity ({units})", lambda p: fin("fy_price", p) * fin("shares_outstanding", p), "num",
           note="Price x shares outstanding at the period end")
    fs.blank()
    fs.text("All statement values are hard-coded inputs from the data source (millions); derived items are marked 'derived' in the source column.", "note")
    if A.ltm:
        fs.text(f"{base_label}: income and cash-flow items are the sum of the four quarters {', '.join(A.ltm_meta.get('quarters', []))}; "
                f"balance-sheet items are as at {A.balance_date}; beginning cash is the ending cash of the quarter before the four.", "note", wrap=True, merge_to=4)
    fs.sh.col_widths = {1: 50, 2: 42}

    # =====================================================================
    # Ratios
    # =====================================================================
    rt = SB(book, RAT, H, labels, dates, nh)
    rt.title("Credit ratio analysis", f"{name} - liquidity, leverage, coverage, profitability and market-based measures")
    rt.header("", units)

    def Rw(key: str, label: str, fn: Callable[[int], Expr], fmt: str = "factor", **kw) -> None:
        rt.row(key, label, lambda p: safe(fn(p)), fmt, **kw)

    rt.section("Building blocks")
    rt.row("wc", "Working capital (current assets - current liabilities)", lambda p: fin("current_assets", p) - fin("current_liabilities", p))
    rt.row("quick_assets", "Quick assets (cash, short-term investments and receivables)", lambda p: fin("cash_and_sti", p) + fin("receivables", p))
    rt.row("net_debt", "Net debt (total debt - cash & short-term investments)", lambda p: fin("total_debt", p) - fin("cash_and_sti", p))
    rt.row("fcf", "Free cash flow (CFO + capex)", lambda p: fin("cfo", p) + fin("capex", p))
    rt.row("ffo", "Funds from operations (net income + D&A, Ohlson's APB 19 measure)", lambda p: fin("net_income", p) + fin("da", p))
    rt.row("ebitda_calc", "EBITDA (EBIT + D&A)", lambda p: fin("operating_income", p) + fin("da", p))
    rt.section("Liquidity")
    Rw("r_current", "Current ratio (x)", lambda p: fin("current_assets", p) / fin("current_liabilities", p), "mult")
    Rw("r_quick", "Quick ratio (x)", lambda p: rat("quick_assets", p) / fin("current_liabilities", p), "mult")
    Rw("r_cash", "Cash ratio (x)", lambda p: fin("cash_and_sti", p) / fin("current_liabilities", p), "mult")
    Rw("r_wc_ta", "Working capital / total assets", lambda p: rat("wc", p) / fin("total_assets", p), "pct")
    rt.row("r_runway", "Cash runway when free cash flow is negative (years of cash burn)",
           lambda p: IF(LT(rat("fcf", p), 0), safe(fin("cash_and_sti", p) / (-rat("fcf", p))), "n/a"), "num1")
    rt.section("Leverage")
    Rw("r_tl_ta", "Total liabilities / total assets", lambda p: fin("total_liabilities", p) / fin("total_assets", p), "pct")
    Rw("r_debt_ta", "Total debt / total assets", lambda p: fin("total_debt", p) / fin("total_assets", p), "pct")
    Rw("r_de", "Debt / equity (x)", lambda p: fin("total_debt", p) / fin("total_equity", p), "mult")
    Rw("r_debt_cap", "Debt / (debt + book equity)", lambda p: fin("total_debt", p) / (fin("total_debt", p) + fin("total_equity", p)), "pct")
    Rw("r_debt_ebitda", "Total debt / EBITDA (x)", lambda p: fin("total_debt", p) / rat("ebitda_calc", p), "mult")
    Rw("r_nd_ebitda", "Net debt / EBITDA (x)", lambda p: rat("net_debt", p) / rat("ebitda_calc", p), "mult")
    Rw("r_ltd_ta", "Long-term debt / total assets", lambda p: fin("long_term_debt", p) / fin("total_assets", p), "pct")
    Rw("r_equity_ta", "Book equity / total assets", lambda p: fin("total_equity", p) / fin("total_assets", p), "pct")
    rt.row("r_neg_equity", "Negative book equity (1 = yes)", lambda p: IF(LE(fin("total_equity", p), 0), 1, 0), "int")
    rt.section("Coverage and debt service")
    rt.row("has_interest", "Interest expense reported (1 = yes)", lambda p: IF(GT(fin("interest_expense", p), 0), 1, 0), "int")
    rt.row("r_int_cov", "Interest coverage: EBIT / interest expense (x)",
           lambda p: IF(GT(fin("interest_expense", p), 0), fin("operating_income", p) / fin("interest_expense", p), "n/a"), "mult")
    rt.row("r_ebitda_cov", "EBITDA / interest expense (x)",
           lambda p: IF(GT(fin("interest_expense", p), 0), rat("ebitda_calc", p) / fin("interest_expense", p), "n/a"), "mult")
    rt.row("r_fccr", "(EBITDA - capex) / interest expense (x)",
           lambda p: IF(GT(fin("interest_expense", p), 0), (rat("ebitda_calc", p) + fin("capex", p)) / fin("interest_expense", p), "n/a"), "mult")
    Rw("r_cfo_debt", "Cash from operations / total debt", lambda p: fin("cfo", p) / fin("total_debt", p), "pct")
    Rw("r_fcf_debt", "Free cash flow / total debt", lambda p: rat("fcf", p) / fin("total_debt", p), "pct")
    rt.row("r_debt_cfo", "Years to repay total debt from cash from operations",
           lambda p: IF(GT(fin("cfo", p), 0), safe(fin("total_debt", p) / fin("cfo", p)), "n/a"), "num1")
    Rw("r_cfo_tl", "Cash from operations / total liabilities", lambda p: fin("cfo", p) / fin("total_liabilities", p), "pct")
    rt.row("r_liq12", "12-month liquidity coverage: (cash & short-term investments + CFO) / (short-term debt + interest expense)",
           lambda p: IF(GT(fin("short_term_debt", p) + fin("interest_expense", p), 0),
                        (fin("cash_and_sti", p) + fin("cfo", p)) / (fin("short_term_debt", p) + fin("interest_expense", p)), "n/a"), "mult")
    rt.section("Profitability")
    Rw("r_roa", "Return on assets (net income / total assets)", lambda p: fin("net_income", p) / fin("total_assets", p), "pct")
    rt.row("r_roe", "Return on equity (n/a when book equity is not positive)",
           lambda p: IF(GT(fin("total_equity", p), 0), fin("net_income", p) / fin("total_equity", p), "n/a"), "pct")
    Rw("r_gross_margin", "Gross margin", lambda p: (fin("revenue", p) - fin("cogs", p)) / fin("revenue", p), "pct")
    Rw("r_ebitda_margin", "EBITDA margin", lambda p: rat("ebitda_calc", p) / fin("revenue", p), "pct")
    Rw("r_ebit_margin", "EBIT margin", lambda p: fin("operating_income", p) / fin("revenue", p), "pct")
    Rw("r_net_margin", "Net margin", lambda p: fin("net_income", p) / fin("revenue", p), "pct")
    rt.section("Efficiency and growth")
    Rw("r_asset_turn", "Asset turnover (revenue / total assets, x)", lambda p: fin("revenue", p) / fin("total_assets", p), "mult")
    Rw("r_dso", "Days sales outstanding", lambda p: fin("receivables", p) / fin("revenue", p) * 365, "days")
    rt.row("r_rev_growth", "Revenue growth", lambda p: safe(fin("revenue", p) / fin("revenue", p - 1) - 1) if p > 0 else None, "pct")
    rt.row("r_ni_growth", "Net income growth", lambda p: safe(fin("net_income", p) / fin("net_income", p - 1) - 1) if p > 0 else None, "pct")
    rt.section("Market-based")
    rt.row("r_mve", f"Market value of equity ({units})", lambda p: fin("mve", p))
    Rw("r_mve_tl", "Market value of equity / total liabilities (x)", lambda p: fin("mve", p) / fin("total_liabilities", p), "mult")
    rt.row("r_ev", f"Enterprise value ({units})", lambda p: fin("mve", p) + fin("total_debt", p) - fin("cash_and_sti", p))
    Rw("r_ev_ebitda", "EV / EBITDA (x)", lambda p: rat("r_ev", p) / rat("ebitda_calc", p), "mult")
    Rw("r_debt_mve", "Total debt / market value of equity (x)", lambda p: fin("total_debt", p) / fin("mve", p), "mult")
    rt.sh.col_widths = {1: 60, 2: 12}

    # =====================================================================
    # DuPont analysis
    # =====================================================================
    du = SB(book, DUP, H, labels, dates, nh)
    du.title("DuPont analysis", f"{name} - return on equity decomposed into margin, asset efficiency and leverage (ending balances)")
    du_hdr = du.r
    du.header("", "")
    te_pos = [((P[p].fields.get("total_equity") or 0.0) > 0) for p in H]   # ROE is undefined with non-positive book equity

    def if_eq(p: int, expr: Expr):
        return expr if te_pos[p] else None

    du_rows: Dict[str, int] = {}

    def DR(key: str, label: str, fn, fmt: str, **kw) -> int:
        du_rows[key] = du.row(key, label, fn, fmt, **kw)
        return du_rows[key]

    du.section("Three-step DuPont: ROE = net margin x asset turnover x equity multiplier")
    DR("d_net_margin", "Net margin (net income / revenue)", lambda p: safe(fin("net_income", p) / fin("revenue", p)), "pct")
    DR("d_asset_turn", "Asset turnover (revenue / total assets, x)", lambda p: safe(fin("revenue", p) / fin("total_assets", p)), "mult")
    DR("d_equity_mult", "Equity multiplier (total assets / book equity, x)", lambda p: if_eq(p, fin("total_assets", p) / fin("total_equity", p)), "mult")
    DR("d_roe", "Return on equity = net margin x asset turnover x equity multiplier",
                   lambda p: if_eq(p, dup("d_net_margin", p) * dup("d_asset_turn", p) * dup("d_equity_mult", p)), "pct", bold=True)
    DR("d_roe_check", "Check: net income / book equity", lambda p: if_eq(p, fin("net_income", p) / fin("total_equity", p)), "pct")
    DR("d_roe_change", "Change in ROE versus the prior year (percentage points)",
           lambda p: (dup("d_roe", p) - dup("d_roe", p - 1)) if (p >= 1 and te_pos[p] and te_pos[p - 1]) else None, "pct")
    du.section("Five-step DuPont: ROE = tax burden x interest burden x EBIT margin x asset turnover x equity multiplier")
    DR("d_tax_burden", "Tax burden (net income / pre-tax income)", lambda p: safe(fin("net_income", p) / fin("pretax_income", p)), "pct")
    DR("d_int_burden", "Interest burden (pre-tax income / EBIT)", lambda p: safe(fin("pretax_income", p) / fin("operating_income", p)), "pct")
    DR("d_ebit_margin", "EBIT margin (EBIT / revenue)", lambda p: safe(fin("operating_income", p) / fin("revenue", p)), "pct")
    DR("d_roe5", "Return on equity (five-step product)",
           lambda p: if_eq(p, dup("d_tax_burden", p) * dup("d_int_burden", p) * dup("d_ebit_margin", p) * dup("d_asset_turn", p) * dup("d_equity_mult", p)), "pct", bold=True)
    du.section("Return on assets and leverage contribution")
    DR("d_roa", "Return on assets = net margin x asset turnover", lambda p: dup("d_net_margin", p) * dup("d_asset_turn", p), "pct", bold=True)
    DR("d_leverage_effect", "Leverage contribution to ROE (ROE - ROA, percentage points)", lambda p: if_eq(p, dup("d_roe", p) - dup("d_roa", p)), "pct")
    DR("d_debt_ta", "Total debt / total assets (memo)", lambda p: safe(fin("total_debt", p) / fin("total_assets", p)), "pct", memo=True)
    du.blank()
    du.text("Ending balances are used so the figures tie to the Ratios sheet. Years with non-positive book equity are left blank: ROE and the equity multiplier "
            "are undefined and a high ROE from a thin equity base is a leverage warning rather than a strength. "
            "The five-step product equals the three-step product whenever pre-tax income and EBIT are non-zero.", "note")
    du_cat = RangeRef(DUP, du_hdr, du.col(0), du_hdr, du.col(L))
    def du_rng(key: str) -> RangeRef:
        return RangeRef(DUP, du_rows[key], du.col(0), du_rows[key], du.col(L))
    du_chart_r = du.r + 2
    book.set(DUP, du_chart_r - 1, 1, "Charts", "text", "section")
    du.sh.charts.extend([
        Chart("dupont_roe", "line", "Return on equity and return on assets by fiscal year", f"A{du_chart_r}",
              [ChartSeries("Return on equity", du_rng("d_roe"), PURPLE), ChartSeries("Return on assets", du_rng("d_roa"), BLUE)], du_cat, "pct", "return",
              note="ROE is blank in years with non-positive book equity."),
        Chart("dupont_margins", "line", "DuPont margin drivers: net margin, EBIT margin, tax and interest burden", f"K{du_chart_r}",
              [ChartSeries("Net margin", du_rng("d_net_margin"), NAVY), ChartSeries("EBIT margin", du_rng("d_ebit_margin"), ORANGE),
               ChartSeries("Tax burden", du_rng("d_tax_burden"), GREEN), ChartSeries("Interest burden", du_rng("d_int_burden"), GOLD)], du_cat, "pct", "ratio"),
        Chart("dupont_leverage", "bar", "DuPont efficiency and leverage: asset turnover and equity multiplier (x)", f"A{du_chart_r + 17}",
              [ChartSeries("Asset turnover", du_rng("d_asset_turn"), BLUE), ChartSeries("Equity multiplier", du_rng("d_equity_mult"), PURPLE)], du_cat, "mult", "x"),
    ])
    du.sh.max_row = max(du.sh.max_row, du_chart_r + 34)
    du.sh.col_widths = {1: 66, 2: 10}

    # =====================================================================
    # Altman Z family
    # =====================================================================
    at = SB(book, ALT, H, labels, dates, nh)
    at.title("Altman Z-score family", f"{name} - Z (1968), Z' (1983) and Z'' (1995); X4 uses the current market capitalisation for {labels[L]} and fiscal-year-end prices before")
    at.header("", "")
    at.section("Components")
    at.row("x1", "X1 = working capital / total assets", lambda p: safe(rat("wc", p) / fin("total_assets", p)), "factor")
    at.row("x2", "X2 = retained earnings / total assets", lambda p: safe(fin("retained_earnings", p) / fin("total_assets", p)), "factor")
    at.row("x3", "X3 = EBIT / total assets", lambda p: safe(fin("operating_income", p) / fin("total_assets", p)), "factor")
    at.row("x4m", "X4 = market value of equity / total liabilities", lambda p: safe(fin("mve", p) / fin("total_liabilities", p)), "factor")
    at.row("x4b", "X4 (book) = book equity / total liabilities", lambda p: safe(fin("total_equity", p) / fin("total_liabilities", p)), "factor")
    at.row("x5", "X5 = sales / total assets", lambda p: safe(fin("revenue", p) / fin("total_assets", p)), "factor")
    at.section("Z-score (1968) - listed manufacturing companies")
    at.row("z", "Altman Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5",
           lambda p: inp("c_z_x1") * alt("x1", p) + inp("c_z_x2") * alt("x2", p) + inp("c_z_x3") * alt("x3", p) + inp("c_z_x4") * alt("x4m", p) + inp("c_z_x5") * alt("x5", p),
           "score", bold=True)
    at.row("z_zone", "Zone (safe > 2.99, grey, distress < 1.81)",
           lambda p: IF(GT(alt("z", p), inp("t_z_safe")), "Safe", IF(LT(alt("z", p), inp("t_z_distress")), "Distress", "Grey")), "text")
    at.section("Z'-score (1983) - private companies (book equity in X4)")
    at.row("z1", "Altman Z' = 0.717 X1 + 0.847 X2 + 3.107 X3 + 0.420 X4 + 0.998 X5",
           lambda p: inp("c_z1_x1") * alt("x1", p) + inp("c_z1_x2") * alt("x2", p) + inp("c_z1_x3") * alt("x3", p) + inp("c_z1_x4") * alt("x4b", p) + inp("c_z1_x5") * alt("x5", p),
           "score", bold=True)
    at.row("z1_zone", "Zone (safe > 2.90, grey, distress < 1.23)",
           lambda p: IF(GT(alt("z1", p), inp("t_z1_safe")), "Safe", IF(LT(alt("z1", p), inp("t_z1_distress")), "Distress", "Grey")), "text")
    at.section("Z''-score (1995) - non-manufacturers and emerging markets")
    at.row("z2", "Altman Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4",
           lambda p: inp("c_z2_x1") * alt("x1", p) + inp("c_z2_x2") * alt("x2", p) + inp("c_z2_x3") * alt("x3", p) + inp("c_z2_x4") * alt("x4b", p),
           "score", bold=True)
    at.row("z2_zone", "Zone (safe > 2.60, grey, distress < 1.10)",
           lambda p: IF(GT(alt("z2", p), inp("t_z2_safe")), "Safe", IF(LT(alt("z2", p), inp("t_z2_distress")), "Distress", "Grey")), "text")
    at.row("em", "EM score = Z'' + 3.25", lambda p: alt("z2", p) + inp("c_z2_const"), "score")
    n_em = len(S.EM_RATING_TABLE)
    at.row("em_rating", "Bond rating equivalent of the EM score (Altman 1996 medians as class floors)", lambda p: lookup_desc(alt("em", p), n_em, lambda i: f"em_lb_{i}", lambda i: f"em_r_{i}"), "text", bold=True)
    at.section(f"Stress test ({labels[L]}): EBIT shocked by the factor on Inputs")
    at.row("z2_stress", "Altman Z'' with stressed EBIT",
           lambda p: inp("c_z2_x1") * alt("x1", p) + inp("c_z2_x2") * alt("x2", p) + inp("c_z2_x3") * alt("x3", p) * (1 + inp("stress_ebit")) + inp("c_z2_x4") * alt("x4b", p),
           "score", periods=[L], bold=True)
    at.row("z2_stress_zone", "Zone under stress",
           lambda p: IF(GT(alt("z2_stress", p), inp("t_z2_safe")), "Safe", IF(LT(alt("z2_stress", p), inp("t_z2_distress")), "Distress", "Grey")), "text", periods=[L])
    at.blank()
    at.text("Z was estimated on US manufacturers; Z'' removes the sales/assets term and is the variant Altman recommends for non-manufacturers and non-US companies. "
            "Negative retained earnings or negative equity push X2 and X4 below zero, which is intended: accumulated losses are a distress signal.", "note")
    at.sh.col_widths = {1: 60, 2: 10}

    # =====================================================================
    # Piotroski F
    # =====================================================================
    pt = SB(book, PIO, H, labels, dates, nh)
    pt.title("Piotroski F-score", f"{name} - nine binary signals of fundamental strength (Piotroski 2000); computed from the second fiscal year")
    pt.header("", "")

    def ta_begin(p: int) -> K:
        return fin("total_assets", p - 1 if p >= 1 else p)

    pt.section("Underlying measures")
    pt.row("roa", "ROA = net income / beginning total assets", lambda p: safe(fin("net_income", p) / ta_begin(p)), "pct")
    pt.row("cfo_ta", "Cash from operations / beginning total assets", lambda p: safe(fin("cfo", p) / ta_begin(p)), "pct")
    pt.row("lever", "Leverage = total debt (long-term debt incl. current portion) / average total assets",
           lambda p: safe(fin("total_debt", p) / ((fin("total_assets", p) + fin("total_assets", p - 1)) / 2)) if p >= 1 else safe(fin("total_debt", p) / fin("total_assets", p)), "pct")
    pt.row("cr", "Current ratio (x)", lambda p: safe(fin("current_assets", p) / fin("current_liabilities", p)), "mult")
    pt.row("gm", "Gross margin", lambda p: safe((fin("revenue", p) - fin("cogs", p)) / fin("revenue", p)), "pct")
    pt.row("ato", "Asset turnover = revenue / beginning total assets (x)", lambda p: safe(fin("revenue", p) / ta_begin(p)), "mult")
    pt.row("issued", "Equity issued in the year (1 = issuance proceeds reported or shares outstanding up more than 1%)",
           lambda p: IF(OR(GT(fin("stock_issued", p), 0), GT(fin("shares_outstanding", p), fin("shares_outstanding", p - 1) * 1.01)), 1, 0) if p >= 1 else None, "int")
    pt.section("Signals (1 = point scored)")
    signals = [
        ("f1", "1. Positive return on assets", lambda p: GT(pio("roa", p), 0)),
        ("f2", "2. Positive cash from operations", lambda p: GT(fin("cfo", p), 0)),
        ("f3", "3. Return on assets improved", lambda p: GT(pio("roa", p), pio("roa", p - 1))),
        ("f4", "4. Cash from operations exceeds net income (accrual quality)", lambda p: GT(pio("cfo_ta", p), pio("roa", p))),
        ("f5", "5. Leverage (total debt / average assets) decreased", lambda p: LT(pio("lever", p), pio("lever", p - 1))),
        ("f6", "6. Current ratio improved", lambda p: GT(pio("cr", p), pio("cr", p - 1))),
        ("f7", "7. No new equity issued", lambda p: EQ(pio("issued", p), 0)),
        ("f8", "8. Gross margin improved", lambda p: GT(pio("gm", p), pio("gm", p - 1))),
        ("f9", "9. Asset turnover improved", lambda p: GT(pio("ato", p), pio("ato", p - 1))),
    ]
    for key, lab, cond in signals:
        pt.row(key, lab, lambda p, c=cond: IF(c(p), 1, 0) if p >= 1 else None, "int")

    def f_total(p: int) -> Expr:
        e: Expr = pio("f1", p)
        for k, _, _ in signals[1:]:
            e = e + pio(k, p)
        return e

    pt.row("f_score", "Piotroski F-score (0-9)", lambda p: f_total(p) if p >= 1 else None, "int", bold=True)
    pt.row("f_class", "Interpretation (strong >= 8, weak <= 2)",
           lambda p: IF(GE(pio("f_score", p), inp("t_f_strong")), "Strong", IF(LE(pio("f_score", p), inp("t_f_weak")), "Weak", "Average")) if p >= 1 else None, "text")
    pt.sh.col_widths = {1: 66, 2: 10}

    # =====================================================================
    # Beneish M
    # =====================================================================
    bt = SB(book, BEN, H, labels, dates, nh)
    bt.title("Beneish M-score", f"{name} - earnings-manipulation probit (Beneish 1999); each index compares the year with the prior year")
    bt.header("", "")
    bt.section("Indices (year t versus t-1; 1.0 = no change)")

    def idx(fn: Callable[[int], Expr], neutral: float = 1.0):
        return lambda p: IFERROR(fn(p), neutral) if p >= 1 else None

    bt.row("dsri", "DSRI - days sales in receivables index", idx(lambda p: (fin("receivables", p) / fin("revenue", p)) / (fin("receivables", p - 1) / fin("revenue", p - 1))), "factor")
    bt.row("gmi", "GMI - gross margin index (prior / current)", idx(lambda p: ((fin("revenue", p - 1) - fin("cogs", p - 1)) / fin("revenue", p - 1)) / ((fin("revenue", p) - fin("cogs", p)) / fin("revenue", p))), "factor")
    bt.row("aqi", "AQI - asset quality index", idx(lambda p: (1 - (fin("current_assets", p) + fin("ppe", p)) / fin("total_assets", p)) / (1 - (fin("current_assets", p - 1) + fin("ppe", p - 1)) / fin("total_assets", p - 1))), "factor")
    bt.row("sgi", "SGI - sales growth index", idx(lambda p: fin("revenue", p) / fin("revenue", p - 1)), "factor")
    bt.row("depi", "DEPI - depreciation index", idx(lambda p: (fin("da", p - 1) / (fin("da", p - 1) + fin("ppe", p - 1))) / (fin("da", p) / (fin("da", p) + fin("ppe", p)))), "factor")
    bt.row("sgai", "SGAI - SG&A expense index", idx(lambda p: (fin("sga", p) / fin("revenue", p)) / (fin("sga", p - 1) / fin("revenue", p - 1))), "factor")
    bt.row("lvgi", "LVGI - leverage index", idx(lambda p: ((fin("long_term_debt", p) + fin("current_liabilities", p)) / fin("total_assets", p)) / ((fin("long_term_debt", p - 1) + fin("current_liabilities", p - 1)) / fin("total_assets", p - 1))), "factor")
    bt.row("tata", "TATA - total accruals / total assets", idx(lambda p: (fin("net_income", p) - fin("cfo", p)) / fin("total_assets", p), 0.0), "factor")
    bt.section("M-score")
    bt.row("m8", "M-score (8 variables)",
           lambda p: (inp("c_m_const") + inp("c_m_dsri") * ben("dsri", p) + inp("c_m_gmi") * ben("gmi", p) + inp("c_m_aqi") * ben("aqi", p)
                      + inp("c_m_sgi") * ben("sgi", p) + inp("c_m_depi") * ben("depi", p) + inp("c_m_sgai") * ben("sgai", p)
                      + inp("c_m_tata") * ben("tata", p) + inp("c_m_lvgi") * ben("lvgi", p)) if p >= 1 else None, "score", bold=True)
    bt.row("m5", "M-score (5 variables)",
           lambda p: (inp("c_m5_const") + inp("c_m5_dsri") * ben("dsri", p) + inp("c_m5_gmi") * ben("gmi", p) + inp("c_m5_aqi") * ben("aqi", p)
                      + inp("c_m5_sgi") * ben("sgi", p) + inp("c_m5_depi") * ben("depi", p)) if p >= 1 else None, "score")
    bt.row("m_prob", "Implied probability of manipulation = N(M)", lambda p: NORMSDIST(ben("m8", p)) if p >= 1 else None, "pct")
    bt.row("m_flag", "Signal (M > -1.78)", lambda p: IF(GT(ben("m8", p), inp("t_m_flag")), "Possible manipulation", "No signal") if p >= 1 else None, "text", bold=True)
    bt.blank()
    bt.text("Indices default to 1.0 (neutral) when a component is zero or not reported (e.g. SG&A not disclosed separately). "
            "The M-score is a screening tool for earnings quality, not evidence of fraud.", "note")
    bt.sh.col_widths = {1: 60, 2: 10}

    # =====================================================================
    # Distress models: Ohlson, Zmijewski, Springate, Grover, Taffler
    # =====================================================================
    dt = SB(book, DIST, H, labels, dates, nh)
    dt.title("Distress prediction models", f"{name} - Ohlson O, Zmijewski X, Springate S, Grover G and Taffler Z")
    dt.header("", "")
    dt.section("Ohlson O-score (1980)")
    dt.row("o_size", "SIZE = ln(total assets in USD x unit multiplier / GNP price index)",
           lambda p: safe(LN(fin("total_assets", p) * inp("fx_to_usd") * inp("ta_scale") / inp("gnp_index"))), "factor")
    dt.row("o_tlta", "TLTA = total liabilities / total assets", lambda p: safe(fin("total_liabilities", p) / fin("total_assets", p)), "factor")
    dt.row("o_wcta", "WCTA = working capital / total assets", lambda p: safe(rat("wc", p) / fin("total_assets", p)), "factor")
    dt.row("o_clca", "CLCA = current liabilities / current assets", lambda p: safe(fin("current_liabilities", p) / fin("current_assets", p)), "factor")
    dt.row("o_oeneg", "OENEG = 1 if total liabilities exceed total assets", lambda p: IF(GT(fin("total_liabilities", p), fin("total_assets", p)), 1, 0), "int")
    dt.row("o_nita", "NITA = net income / total assets", lambda p: safe(fin("net_income", p) / fin("total_assets", p)), "factor")
    dt.row("o_futl", "FUTL = funds from operations / total liabilities", lambda p: safe(rat("ffo", p) / fin("total_liabilities", p)), "factor")
    dt.row("o_intwo", "INTWO = 1 if net loss in both of the last two years",
           lambda p: IF(AND(LT(fin("net_income", p), 0), LT(fin("net_income", p - 1), 0)), 1, 0) if p >= 1 else None, "int")
    dt.row("o_chin", "CHIN = (NI(t) - NI(t-1)) / (|NI(t)| + |NI(t-1)|)",
           lambda p: safe((fin("net_income", p) - fin("net_income", p - 1)) / (ABS(fin("net_income", p)) + ABS(fin("net_income", p - 1)))) if p >= 1 else None, "factor")
    dt.row("o_score", "Ohlson O-score",
           lambda p: (inp("c_o_const") + inp("c_o_size") * dis("o_size", p) + inp("c_o_tlta") * dis("o_tlta", p) + inp("c_o_wcta") * dis("o_wcta", p)
                      + inp("c_o_clca") * dis("o_clca", p) + inp("c_o_oeneg") * dis("o_oeneg", p) + inp("c_o_nita") * dis("o_nita", p)
                      + inp("c_o_futl") * dis("o_futl", p) + inp("c_o_intwo") * dis("o_intwo", p) + inp("c_o_chin") * dis("o_chin", p)) if p >= 1 else None,
           "score", bold=True)
    dt.row("o_pd", "Probability of bankruptcy = e^O / (1 + e^O)",
           lambda p: IF(GT(dis("o_score", p), 30), 1, IF(LT(dis("o_score", p), -30), 0, EXP(dis("o_score", p)) / (1 + EXP(dis("o_score", p))))) if p >= 1 else None, "pct2", bold=True)
    dt.row("o_flag", "Classification (probability above the cut-off on Inputs; Ohlson's optimal 3.8%)", lambda p: IF(GT(dis("o_pd", p), inp("t_o_pd")), "Distress", "Not distressed") if p >= 1 else None, "text")
    dt.section("Zmijewski X-score (1984)")
    dt.row("x_roa", "ROA = net income / total assets", lambda p: safe(fin("net_income", p) / fin("total_assets", p)), "factor")
    dt.row("x_finl", "FINL = total liabilities / total assets", lambda p: safe(fin("total_liabilities", p) / fin("total_assets", p)), "factor")
    dt.row("x_liq", "LIQ = current assets / current liabilities", lambda p: safe(fin("current_assets", p) / fin("current_liabilities", p)), "factor")
    dt.row("x_score", "Zmijewski X-score", lambda p: inp("c_x_const") + inp("c_x_roa") * dis("x_roa", p) + inp("c_x_finl") * dis("x_finl", p) + inp("c_x_liq") * dis("x_liq", p), "score", bold=True)
    dt.row("x_pd", "Probability of distress = N(X)", lambda p: NORMSDIST(dis("x_score", p)), "pct2", bold=True)
    dt.row("x_flag", "Classification (probability > 50%)", lambda p: IF(GT(dis("x_pd", p), inp("t_x_pd")), "Distress", "Not distressed"), "text")
    dt.section("Springate S-score (1978)")
    dt.row("s_a", "A = working capital / total assets", lambda p: safe(rat("wc", p) / fin("total_assets", p)), "factor")
    dt.row("s_b", "B = EBIT / total assets", lambda p: safe(fin("operating_income", p) / fin("total_assets", p)), "factor")
    dt.row("s_c", "C = pre-tax income / current liabilities", lambda p: safe(fin("pretax_income", p) / fin("current_liabilities", p)), "factor")
    dt.row("s_d", "D = sales / total assets", lambda p: safe(fin("revenue", p) / fin("total_assets", p)), "factor")
    dt.row("s_score", "Springate S-score", lambda p: inp("c_s_a") * dis("s_a", p) + inp("c_s_b") * dis("s_b", p) + inp("c_s_c") * dis("s_c", p) + inp("c_s_d") * dis("s_d", p), "score", bold=True)
    dt.row("s_flag", "Classification (S < 0.862 = likely failure)", lambda p: IF(LT(dis("s_score", p), inp("t_s_cut")), "Likely failure", "Healthy"), "text")
    dt.section("Grover G-score (2001)")
    dt.row("g_x1", "X1 = working capital / total assets", lambda p: safe(rat("wc", p) / fin("total_assets", p)), "factor")
    dt.row("g_x3", "X3 = EBIT / total assets", lambda p: safe(fin("operating_income", p) / fin("total_assets", p)), "factor")
    dt.row("g_roa", "ROA = net income / total assets", lambda p: safe(fin("net_income", p) / fin("total_assets", p)), "factor")
    dt.row("g_score", "Grover G-score", lambda p: inp("c_g_x1") * dis("g_x1", p) + inp("c_g_x3") * dis("g_x3", p) + inp("c_g_roa") * dis("g_roa", p) + inp("c_g_const"), "score", bold=True)
    dt.row("g_flag", "Classification (<= -0.02 bankrupt zone, >= 0.01 healthy)",
           lambda p: IF(LE(dis("g_score", p), inp("t_g_bankrupt")), "Bankrupt zone", IF(GE(dis("g_score", p), inp("t_g_healthy")), "Healthy", "Grey")), "text")
    dt.section("Taffler Z-score (1983)")
    dt.row("t_x1", "X1 = pre-tax profit / current liabilities", lambda p: safe(fin("pretax_income", p) / fin("current_liabilities", p)), "factor")
    dt.row("t_x2", "X2 = current assets / total liabilities", lambda p: safe(fin("current_assets", p) / fin("total_liabilities", p)), "factor")
    dt.row("t_x3", "X3 = current liabilities / total assets", lambda p: safe(fin("current_liabilities", p) / fin("total_assets", p)), "factor")
    dt.row("t_x4", "X4 = no-credit interval (days) = (current assets - inventory - current liabilities) / daily operating costs",
           lambda p: safe((fin("current_assets", p) - fin("inventory", p) - fin("current_liabilities", p)) / ((fin("revenue", p) - fin("pretax_income", p) - fin("da", p)) / 365)), "num1")
    dt.row("t_score", "Taffler Z-score", lambda p: inp("c_t_const") + inp("c_t_x1") * dis("t_x1", p) + inp("c_t_x2") * dis("t_x2", p) + inp("c_t_x3") * dis("t_x3", p) + inp("c_t_x4") * dis("t_x4", p), "score", bold=True)
    dt.row("t_flag", "Classification (Z < 0 = at risk)", lambda p: IF(LT(dis("t_score", p), inp("t_t_cut")), "At risk", "Solvent"), "text")
    dt.sh.col_widths = {1: 66, 2: 10}

    # =====================================================================
    # Merton PD
    # =====================================================================
    mt = SB(book, MER, [], labels, dates, nh)
    daily = ds.daily_prices is not None and len(ds.daily_prices.closes) >= 30
    px = ds.daily_prices if daily else ds.stock_prices
    n_px = len(px.closes)
    data_r0 = 70   # the price table starts here; the scalar block above must stay shorter (asserted below)
    ret_rng = RangeRef(MER, data_r0 + 1, 3, data_r0 + n_px - 1, 3)
    mt.title("Merton structural model and distance to default",
             f"{name} - naive DD (Bharath & Shumway 2008) and the iterated two-equation Merton solve; {n_px} {'daily' if daily else 'monthly'} prices")

    def sc(key: str, label: str, content: Any, fmt: str = "num", basis: str = "", bold: bool = False, style: Optional[str] = None) -> None:
        mt.scalar(key, label, content, fmt, basis=basis, bold=bold, style=style)

    mt.text(f"Inputs ({base_label} balance sheet at {A.balance_date}, current market data)", "section")
    sc("E", f"Market value of equity E ({units})", inp("market_cap"), "num", basis="Inputs: price x shares")
    sc("std", f"Short-term debt and current leases ({units})", fin("short_term_debt", L))
    sc("ltd", f"Long-term debt and leases ({units})", fin("long_term_debt", L))
    sc("tdebt", f"Total debt ({units})", fin("total_debt", L))
    sc("tl", f"Total liabilities ({units})", fin("total_liabilities", L))
    sc("F", f"Default point F ({units})", IF(EQ(inp("default_point_method"), 1), mer("std") + inp("c_dd_lt_share") * mer("ltd"),
                                              IF(EQ(inp("default_point_method"), 2), mer("tdebt"), mer("tl"))), "num",
       basis="Method per Inputs: KMV (short-term debt + 0.5 x long-term debt), total debt or total liabilities", bold=True)
    sc("F_eff", "F used in the formulas (floored at 0.000001 so debt-free companies still compute)", MAX(mer("F"), 0.000001), "num")
    sc("r", "Risk-free rate r", inp("risk_free"), "pct2")
    sc("T", "Horizon T (years)", inp("horizon"), "num2")
    sc("ann", "Return periods per year (annualisation of volatility)", inp("c_dd_trading_days") if daily else 12.0, "int",
       basis="Trading days (daily prices)" if daily else "Monthly prices: 12 periods per year (daily data unavailable)", style=None if daily else "input")
    mt.text("Equity volatility and trailing return (from the price table below)", "section")
    sc("n_ret", "Return observations", COUNT(ret_rng), "int", basis="COUNT of log returns")
    sc("vol_calc", "Annualised volatility of log returns", IFERROR(STDEV(ret_rng) * SQRT(mer("ann")), inp("equity_vol_manual")), "pct",
       basis="STDEV(log returns) x sqrt(periods per year)")
    sc("ret_calc", "Trailing return over the price window", CellRef(MER, data_r0 + n_px - 1, 2) / CellRef(MER, data_r0, 2) - 1, "pct",
       basis="Last close / first close - 1")
    sc("sigma_E", "Equity volatility sigma_E used", IF(EQ(inp("equity_vol_method"), 1), mer("vol_calc"), inp("equity_vol_manual")), "pct", bold=True)
    sc("mu", "Expected asset return mu used", IF(EQ(inp("mu_method"), 1), mer("ret_calc"), IF(EQ(inp("mu_method"), 2), mer("r"), inp("mu_manual"))), "pct",
       basis="Method per Inputs")
    mt.text("Naive distance to default (Bharath & Shumway 2008)", "section")
    sc("sigma_D", "Naive debt volatility = 0.05 + 0.25 x sigma_E", inp("c_dd_sd_a") + inp("c_dd_sd_b") * mer("sigma_E"), "pct")
    sc("sigma_V_naive", "Naive asset volatility = E/(E+F) sigma_E + F/(E+F) sigma_D",
       mer("E") / (mer("E") + mer("F_eff")) * mer("sigma_E") + mer("F_eff") / (mer("E") + mer("F_eff")) * mer("sigma_D"), "pct")
    sc("dd_naive", "Naive distance to default (standard deviations)",
       (LN((mer("E") + mer("F_eff")) / mer("F_eff")) + (mer("mu") - 0.5 * mer("sigma_V_naive") ** 2) * mer("T")) / (mer("sigma_V_naive") * SQRT(mer("T"))),
       "score", basis="[ln((E+F)/F) + (mu - sigma_V^2/2) T] / (sigma_V sqrt(T))", bold=True)
    sc("pd_naive", "Naive probability of default = N(-DD)", NORMSDIST(-mer("dd_naive")), "pct2", bold=True)
    sc("dd_naive_rf", "Naive distance to default with mu = risk-free rate (momentum removed)",
       (LN((mer("E") + mer("F_eff")) / mer("F_eff")) + (mer("r") - 0.5 * mer("sigma_V_naive") ** 2) * mer("T")) / (mer("sigma_V_naive") * SQRT(mer("T"))), "score")
    sc("pd_naive_rf", "Naive probability of default with mu = risk-free rate", NORMSDIST(-mer("dd_naive_rf")), "pct2")
    mt.text("Iterated Merton model (asset value and volatility solved in Python; formulas below re-derive equity value and volatility as a check)", "section")
    E_val = R.values["price"] * R.values["shares_outstanding"]
    fl = P[L].fields
    std_v, ltd_v = (fl.get("short_term_debt") or 0.0) / M, (fl.get("long_term_debt") or 0.0) / M
    F_val = {1: std_v + S.MERTON.coefs[2].value * ltd_v, 2: (fl.get("total_debt") or 0.0) / M, 3: (fl.get("total_liabilities") or 0.0) / M}[int(R.values["default_point_method"])]
    sigma_E_val = R.stats["vol"] if int(R.values["equity_vol_method"]) == 1 else float(R.values["equity_vol_manual"])
    sol = solve_merton(E_val, sigma_E_val, F_val, float(R.values["risk_free"]), float(R.values["horizon"]))
    if sol is None:
        V_solved, sV_solved = E_val, sigma_E_val
        solver_text = "No debt at the default point (or non-positive equity): asset value = equity value and asset volatility = equity volatility."
    else:
        V_solved, sV_solved = sol.asset_value, sol.asset_vol
        solver_text = (f"Solved in {sol.iterations} iterations ({'converged' if sol.converged else 'NOT converged'}); residuals "
                       f"{sol.residual_equity:.1e} (equity) and {sol.residual_vol:.1e} (volatility) versus inputs E = {E_val:,.1f}, sigma_E = {sigma_E_val:.2%}, F = {F_val:,.1f}.")
    sc("V", f"Asset value V ({units}) - solver output", float(V_solved), "num", style="input", basis="Python solver (fintea.risk.merton); re-checked by the formulas below", bold=True)
    sc("sigma_V", "Asset volatility sigma_V - solver output", float(sV_solved), "pct", style="input", basis="Python solver; re-checked below", bold=True)
    sc("d1", "d1 = [ln(V/F) + (r + sigma_V^2/2) T] / (sigma_V sqrt(T))",
       (LN(mer("V") / mer("F_eff")) + (mer("r") + 0.5 * mer("sigma_V") ** 2) * mer("T")) / (mer("sigma_V") * SQRT(mer("T"))), "score3")
    sc("d2", "d2 = d1 - sigma_V sqrt(T)", mer("d1") - mer("sigma_V") * SQRT(mer("T")), "score3")
    sc("E_model", f"Equity value implied by (V, sigma_V): V N(d1) - F e^(-rT) N(d2) ({units})",
       mer("V") * NORMSDIST(mer("d1")) - mer("F_eff") * EXP(-mer("r") * mer("T")) * NORMSDIST(mer("d2")), "num")
    sc("sigmaE_model", "Equity volatility implied: (V / E) N(d1) sigma_V", safe(mer("V") * NORMSDIST(mer("d1")) * mer("sigma_V") / mer("E_model")), "pct")
    sc("chk_E", "Check: implied equity value / market equity - 1 (must be ~0)", safe(mer("E_model") / mer("E") - 1), "pct4")
    sc("chk_vol", "Check: implied equity volatility / sigma_E - 1 (must be ~0)", safe(mer("sigmaE_model") / mer("sigma_E") - 1), "pct4")
    sc("lev_mkt", "Market leverage F / V", safe(mer("F_eff") / mer("V")), "pct")
    sc("dd_rn", "Risk-neutral distance to default = d2", mer("d2"), "score")
    sc("pd_rn", "Risk-neutral probability of default = N(-d2)", NORMSDIST(-mer("d2")), "pct2", bold=True)
    sc("dd_phys", "Distance to default with the expected asset return mu", (LN(mer("V") / mer("F_eff")) + (mer("mu") - 0.5 * mer("sigma_V") ** 2) * mer("T")) / (mer("sigma_V") * SQRT(mer("T"))), "score")
    sc("pd_phys", "Probability of default with mu = N(-DD)", NORMSDIST(-mer("dd_phys")), "pct2", bold=True)
    sc("solver_note", "Solver diagnostics", solver_text, "text", style="note")

    def naive_pd_expr(E_x: Expr, sig_x: Expr) -> Expr:
        sD = inp("c_dd_sd_a") + inp("c_dd_sd_b") * sig_x
        sV = E_x / (E_x + mer("F_eff")) * sig_x + mer("F_eff") / (E_x + mer("F_eff")) * sD
        dd = (LN((E_x + mer("F_eff")) / mer("F_eff")) + (mer("mu") - 0.5 * sV ** 2) * mer("T")) / (sV * SQRT(mer("T")))
        return NORMSDIST(-dd)

    mt.text("Stress test of the naive probability of default (shocks on Inputs; same expected return)", "section")
    sc("stress_E", f"Stressed market equity ({units})", mer("E") * (1 + inp("stress_equity")), "num")
    sc("stress_sigma", "Stressed equity volatility", mer("sigma_E") * (1 + inp("stress_vol")), "pct")
    sc("pd_stress_equity", "Naive PD after the equity shock", naive_pd_expr(mer("stress_E"), mer("sigma_E")), "pct2")
    sc("pd_stress_vol", "Naive PD after the volatility shock", naive_pd_expr(mer("E"), mer("stress_sigma")), "pct2")
    sc("pd_stress_both", "Naive PD after both shocks", naive_pd_expr(mer("stress_E"), mer("stress_sigma")), "pct2", bold=True)
    sc("expected_loss", "Expected loss rate = naive PD x (1 - recovery rate)", mer("pd_naive") * (1 - inp("recovery_rate")), "pct2")
    mt.blank()
    mt.text("Risk-neutral probabilities (drift = risk-free rate) are what bond and CDS prices embed and overstate real-world default frequencies; "
            "the naive DD with the prior-year equity return is the Bharath-Shumway forecast that performed as well as the full KMV iteration. "
            "Neither is a rating-agency default rate: treat them as market-implied signals.", "note")
    assert mt.r < data_r0 - 2, f"Merton scalar block ({mt.r} rows) overlaps the price table at row {data_r0}"
    # price table
    book.set(MER, data_r0 - 2, 1, f"Price data ({'daily' if daily else 'monthly'} adjusted close, {px.dates[0]} to {px.dates[-1]})", "text", "section")
    for c, t in enumerate(["Date", f"{sym} adjusted close", "Log return"], start=1):
        book.set(MER, data_r0 - 1, c, t, "text", "header")
    for i in range(n_px):
        r = data_r0 + i
        book.set(MER, r, 1, px.dates[i], "text", "input")
        book.set(MER, r, 2, float(px.closes[i]), "price", "input")
        if i > 0:
            book.set(MER, r, 3, IFERROR(LN(CellRef(MER, r, 2) / CellRef(MER, r - 1, 2)), 0), "pct2", "formula")
    mt.sh.col_widths = {1: 74, 2: 16, 3: 16}
    mt.sh.freeze = f"A{data_r0}"

    # =====================================================================
    # Synthetic rating
    # =====================================================================
    rs = SB(book, RTG, [], labels, dates, nh)
    rs.title("Synthetic credit rating and rating-implied default rates",
             f"{name} - interest coverage mapped to a rating (Damodaran), cross-checked with the Altman EM score; historical default rates by rating class")

    def rc(key: str, label: str, content: Any, fmt: str = "num", basis: str = "", bold: bool = False, style: Optional[str] = None) -> None:
        rs.scalar(key, label, content, fmt, basis=basis, bold=bold, style=style)

    rs.text(f"Interest coverage ({labels[L]})", "section")
    rc("ebit", f"EBIT ({units})", fin("operating_income", L))
    rc("interest", f"Interest expense ({units})", fin("interest_expense", L))
    rc("debt_free", "Debt-free (total debt is zero) with positive EBIT (1 = yes)",
       IF(AND(LE(fin("total_debt", L), 0), GT(rtg("ebit"), 0)), 1, 0), "int", basis="Damodaran rates a company with no interest expense and no debt AAA")
    rc("has_interest", "Coverage available (interest expense reported, or debt-free) (1 = yes)",
       IF(OR(EQ(rat("has_interest", L), 1), EQ(rtg("debt_free"), 1)), 1, 0), "int")
    rc("coverage", "Interest coverage ratio (EBIT / interest expense; 100,000 when debt-free)",
       IF(GT(rtg("interest"), 0), rtg("ebit") / rtg("interest"), IF(EQ(rtg("debt_free"), 1), 100000, 0)), "mult",
       basis="Zero when interest expense is not reported although the company carries debt; the rating then uses the fallback on Inputs", bold=True)
    rc("mcap_usd_bn", "Market capitalisation (USD billions)", inp("market_cap_usd_bn"), "num2")
    rc("is_large", "Large-firm table (1 = yes)", inp("is_large"), "int")
    rs.text("Rating", "section")
    nl, ns = len(S.DAMODARAN_LARGE), len(S.DAMODARAN_SMALL)
    rc("rating_large", "Coverage-based rating - large-firm table", lookup_desc(rtg("coverage"), nl, lambda i: f"rt_l_lb_{i}", lambda i: f"rt_l_r_{i}"), "text")
    rc("rating_small", "Coverage-based rating - small-firm table", lookup_desc(rtg("coverage"), ns, lambda i: f"rt_s_lb_{i}", lambda i: f"rt_s_r_{i}"), "text")
    rc("rating_cov", "Coverage-based rating (table selected by size)", IF(EQ(rtg("is_large"), 1), rtg("rating_large"), rtg("rating_small")), "text")
    rc("rating_em", "Altman EM-score rating equivalent", alt("em_rating", L), "text")
    bbb_idx = S.RATING_ORDER.index("BBB")
    avg_debt = (fin("total_debt", L) + fin("total_debt", L - 1)) / 2 if has_prior else fin("total_debt", L)
    rc("interest_est", f"Estimated interest expense = average total debt x (risk-free + BBB spread) ({units})", avg_debt * (inp("risk_free") + K(INP, f"sp_s_{bbb_idx}")), "num",
       basis="Used only when the source does not report interest expense and the fallback on Inputs is set to 2")
    rc("coverage_est", "Interest coverage on estimated interest", IF(GT(rtg("interest_est"), 0), rtg("ebit") / rtg("interest_est"), 0), "mult")
    rc("rating_est", "Coverage-based rating on estimated interest (table per size)",
       IF(EQ(rtg("is_large"), 1), lookup_desc(rtg("coverage_est"), nl, lambda i: f"rt_l_lb_{i}", lambda i: f"rt_l_r_{i}"),
          lookup_desc(rtg("coverage_est"), ns, lambda i: f"rt_s_lb_{i}", lambda i: f"rt_s_r_{i}")), "text")
    n_avg = min(3, nh)
    ebit_avg: Expr = fin("operating_income", L)
    for q in range(1, n_avg):
        ebit_avg = ebit_avg + fin("operating_income", L - q)
    ebit_avg = ebit_avg / n_avg
    rc("coverage_avg3", f"Interest coverage on average EBIT of the last {n_avg} fiscal year(s) (Damodaran's advice for atypical years; 100,000 when debt-free)",
       IF(GT(rtg("interest"), 0), ebit_avg / rtg("interest"), IF(EQ(rtg("debt_free"), 1), 100000, 0)), "mult")
    rc("rating_avg3", "Rating on average EBIT (information only)",
       IF(EQ(rtg("is_large"), 1), lookup_desc(rtg("coverage_avg3"), nl, lambda i: f"rt_l_lb_{i}", lambda i: f"rt_l_r_{i}"),
          lookup_desc(rtg("coverage_avg3"), ns, lambda i: f"rt_s_lb_{i}", lambda i: f"rt_s_r_{i}")), "text")
    NA_FIN = "n/a (financial institution)"
    if financial:
        # Damodaran rates financial-service firms on long-term interest coverage, which the data source cannot separate,
        # and EBIT / total interest is meaningless for a deposit-funded balance sheet: the rating is not applicable.
        rc("rating", "Synthetic rating used", NA_FIN, "text", bold=True,
           basis="Financial institution: interest is an operating cost, so the coverage-based rating and the EM-score look-alike are not meaningful", style="note")
        rc("rating_source", "Basis of the rating", "Not applicable: financial institution (see the caveat on the Assessment sheet)", "text", style="note")
    else:
        rc("rating", "Synthetic rating used",
           IF(EQ(rtg("has_interest"), 1), rtg("rating_cov"), IF(EQ(inp("interest_fallback"), 2), rtg("rating_est"), rtg("rating_em"))), "text", bold=True,
           basis="Coverage-based when interest expense is reported; otherwise the fallback chosen on Inputs")
        rc("rating_source", "Basis of the rating",
           IF(EQ(rtg("has_interest"), 1), "Interest coverage (Damodaran table)",
              IF(EQ(inp("interest_fallback"), 2), "Coverage on estimated interest (debt x (risk-free + BBB spread))", "Altman EM score (interest expense not reported)")), "text")
    n_sp = len(S.RATING_ORDER)
    if financial:
        rc("spread", "Default spread over the risk-free rate", NA_FIN, "text", style="note")
        rc("kd", "Rating-implied pre-tax cost of debt = risk-free + spread", NA_FIN, "text", style="note")
    else:
        rc("spread", "Default spread over the risk-free rate", lookup_eq(rtg("rating"), n_sp, lambda i: f"sp_r_{i}", lambda i: f"sp_s_{i}", S.SPREAD_BY_RATING["D"]), "pct2")
        rc("kd", "Rating-implied pre-tax cost of debt = risk-free + spread", inp("risk_free") + rtg("spread"), "pct2", bold=True)
    cls_expr: Expr = lift("D")
    for cls, members in reversed(RATING_CLASSES):
        cls_expr = IF(OR(*[EQ(rtg("rating"), m) for m in members]), cls, cls_expr)
    rc("rating_class", "Rating class for the default-rate lookup", cls_expr, "text")

    def dr_lookup(h: str) -> Expr:
        e: Expr = lift(1.0)   # D = defaulted
        for i in reversed(range(len(dr_classes))):
            e = IF(EQ(rtg("rating_class"), K(INP, f"dr_cls_{i}")), K(INP, f"dr_{dr_classes[i]}_{h}"), e)
        return e

    rs.text("Rating-implied historical default rates (average cumulative default rates of the rating class)", "section")
    if financial:
        rc("pd_1y", "1-year default rate of the rating class", NA_FIN, "text", style="note")
        rc("pd_5y", "5-year cumulative default rate of the rating class", NA_FIN, "text", style="note")
        rc("rating_notch", f"Rating notch (0 = AAA ... {len(S.RATING_ORDER) - 1} = D)", 0.0, "int", style="input",
           basis="Not applicable to a financial institution (carries no weight in the index)")
    else:
        rc("pd_1y", "1-year default rate of the rating class", dr_lookup("1"), "pct2", bold=True)
        rc("pd_5y", "5-year cumulative default rate of the rating class", dr_lookup("5"), "pct2", bold=True)
        notch: Expr = lift(len(S.RATING_ORDER) - 1)
        for i in reversed(range(len(S.RATING_ORDER))):
            notch = IF(EQ(rtg("rating"), S.RATING_ORDER[i]), i, notch)
        rc("rating_notch", f"Rating notch (0 = AAA ... {len(S.RATING_ORDER) - 1} = D)", notch, "int")
    rs.text("Market-quoted credit (optional inputs)", "section")
    rc("cds_spread", "CDS or bond spread entered on Inputs (0 = none)", inp("cds_spread"), "pct2")
    rc("recovery", "Assumed recovery rate", inp("recovery_rate"), "pct")
    rc("pd_cds", "Spread-implied annual default probability = spread / (1 - recovery)",
       IF(GT(rtg("cds_spread"), 0), rtg("cds_spread") / (1 - rtg("recovery")), "n/a"), "pct2", bold=True)
    rs.blank()
    rs.text("A synthetic rating is an estimate from one ratio; agencies also weigh business risk, scale, cash flow stability and management. "
            "Default rates are long-run global averages for the letter class, not company-specific probabilities.", "note")
    rs.sh.col_widths = {1: 66, 2: 16, 3: 60}

    # =====================================================================
    # Dashboard
    # =====================================================================
    db = SB(book, DASH, [], labels, dates, nh)
    db.title("Default risk dashboard", f"{name} ({sym}) - composite score, probabilities of default, model verdicts and charts; {units}")
    db.text("Distress signal index (0 = minimal ... 100 = severe) - an uncalibrated weighted average of model signals, not a probability of default", "section")
    hdr(DASH, db, ["Signal", "Latest value", "Sub-score (0-100)", "Weight", "Weighted contribution"])
    comp_r0 = db.r
    ln_lo, ln_hi = 0.0001, 0.20
    acct = not financial   # accounting-ratio models and the coverage rating are not meaningful for financial institutions
    sig_defs = [
        ("sig_z2", "Altman Z'' (zone-scaled)", alt("z2", L), "score",
         100 * MAX(0, MIN(1, (inp("t_z2_safe") - alt("z2", L)) / (inp("t_z2_safe") - inp("t_z2_distress")))), "w_z2", acct),
        ("sig_merton", "Merton naive probability of default", mer("pd_naive"), "pct2",
         100 * MAX(0, MIN(1, (LN(MAX(mer("pd_naive"), 0.000001)) - LN(ln_lo)) / (LN(ln_hi) - LN(ln_lo)))), "w_merton", True),
        ("sig_ohlson", "Ohlson O-score", prior(DIST, "o_score", L), "score",
         100 * MAX(0, MIN(1, (dis("o_score", L) + 6.5) / 6.5)) if has_prior else lift(0), "w_ohlson", has_prior and acct),
        ("sig_rating", "Synthetic rating", rtg("rating"), "text", rtg("rating_notch") / (len(S.RATING_ORDER) - 1) * 100, "w_rating", acct),
        ("sig_zmij", "Zmijewski X-score", dis("x_score", L), "score", 100 * MAX(0, MIN(1, (dis("x_score", L) + 3) / 3)), "w_zmijewski", acct),
        ("sig_pio", "Piotroski F-score (inverted)", prior(PIO, "f_score", L), "int",
         100 * (9 - pio("f_score", L)) / 9 if has_prior else lift(0), "w_piotroski", has_prior and acct),
        ("sig_cons", "Springate / Grover / Taffler distress flags (0-3)",
         IF(EQ(dis("s_flag", L), "Likely failure"), 1, 0) + IF(EQ(dis("g_flag", L), "Bankrupt zone"), 1, 0) + IF(EQ(dis("t_flag", L), "At risk"), 1, 0), "int",
         None, "w_consensus", acct),
    ]
    for key, label, value, fmt, sub, wkey, available in sig_defs:
        r = db.r
        why_na = "" if available else (" - not applicable to a financial institution" if not acct else " - not available with a single fiscal year")
        book.set(DASH, r, 1, label + why_na, "text", "label", indent=1)
        book.set(DASH, r, 2, value, fmt, "link" if isinstance(value, K) else "formula", key=f"{key}_value")
        if sub is None:
            sub = dsh(f"{key}_value") / 3 * 100
        book.set(DASH, r, 3, sub, "num1", "formula", key=f"{key}_sub")
        book.set(DASH, r, 4, inp(wkey) if available else 0.0, "pct", "link" if available else "input", key=f"{key}_w")
        book.set(DASH, r, 5, dsh(f"{key}_sub") * dsh(f"{key}_w"), "num1", "formula", key=f"{key}_contrib")
        db.r += 1
    comp_r1 = db.r - 1
    contrib_sum: Expr = dsh("sig_z2_contrib")
    w_used: Expr = dsh("sig_z2_w")
    for key, *_ in sig_defs[1:]:
        contrib_sum = contrib_sum + dsh(f"{key}_contrib")
        w_used = w_used + dsh(f"{key}_w")
    r = db.r
    book.set(DASH, r, 1, "Distress signal index (weighted average of the sub-scores)", "text", "total", bold=True)
    book.set(DASH, r, 3, safe(contrib_sum / dsh("composite_w")), "num1", "total", key="composite_score", bold=True)
    book.set(DASH, r, 4, w_used, "pct", "formula", key="composite_w")
    db.r += 1
    grade: Expr = lift(S.GRADES[-1][1])
    for lo, g in reversed(S.GRADES[:-1]):
        grade = IF(GE(dsh("composite_score"), lo), g, grade)
    db.scalar("composite_grade", "Index band (Minimal < 20, Low < 40, Moderate < 60, High < 80, Severe)", grade, "text", bold=True, col=3)
    avail = [key for key, *rest in sig_defs if rest[-1]]
    eq_sum: Expr = dsh(f"{avail[0]}_sub")
    for key in avail[1:]:
        eq_sum = eq_sum + dsh(f"{key}_sub")
    db.scalar("composite_equal", f"Equal-weight alternative (mean of the {len(avail)} available sub-scores)", eq_sum / len(avail), "num1", col=3)
    if financial:
        # accounting-ratio models are not applicable to banks and insurers: only the market-implied signal is counted
        votes: Expr = IF(LT(mer("dd_naive"), 1.5), 1, 0)
        n_vote_models = 1
    else:
        votes = IF(EQ(alt("z2_zone", L), "Distress"), 1, 0) + IF(EQ(dis("x_flag", L), "Distress"), 1, 0) + IF(EQ(dis("s_flag", L), "Likely failure"), 1, 0) \
            + IF(EQ(dis("g_flag", L), "Bankrupt zone"), 1, 0) + IF(EQ(dis("t_flag", L), "At risk"), 1, 0) + IF(LT(mer("dd_naive"), 1.5), 1, 0)
        n_vote_models = 6
        if has_prior:
            votes = votes + IF(EQ(dis("o_flag", L), "Distress"), 1, 0)
            n_vote_models = 7
    db.scalar("agreement", f"Model agreement: number of the {n_vote_models} applicable distress model{'s' if n_vote_models != 1 else ''} signalling distress"
              + (" (market-implied Merton only: accounting models are not applicable to a financial institution)" if financial else ""), votes, "int", bold=True, col=3)
    db.scalar("agreement_n", "Distress models counted", n_vote_models, "int", col=3, style="input")
    db.blank()
    db.text("Probability of default by model", "section")
    hdr(DASH, db, ["Model", "Probability", "Horizon", "Nature of the estimate"])
    pd_r0 = db.r
    pd_rows = [
        ("pdt_naive", "Merton naive DD (Bharath-Shumway)", mer("pd_naive"), "1 year", "Market-implied, expected return = trailing equity return"),
        ("pdt_rn", "Merton iterated, risk-neutral", mer("pd_rn"), "1 year", "Market-implied under the risk-free drift (upper bound)"),
        ("pdt_phys", "Merton iterated, physical", mer("pd_phys"), "1 year", "Market-implied with the expected asset return"),
        ("pdt_ohlson", "Ohlson O-score", prior(DIST, "o_pd", L), "1 year", "Accounting logit calibrated on 1970-76 US bankruptcies"),
        ("pdt_zmij", "Zmijewski X-score", dis("x_pd", L), "1 year", "Accounting probit calibrated on 1972-78 US data"),
        ("pdt_r1", "Synthetic rating - historical default rate (1-year)", rtg("pd_1y"), "1 year", "Long-run average default rate of the rating class"),
        ("pdt_r5", "Synthetic rating - historical default rate (5-year)", rtg("pd_5y"), "5 years", "Cumulative average default rate of the rating class"),
    ]
    pd_rows.insert(1, ("pdt_naive_rf", "Merton naive DD, risk-free drift", mer("pd_naive_rf"), "1 year", "Market-implied without the trailing-return momentum term"))
    if float(R.values.get("cds_spread", 0) or 0) > 0:
        pd_rows.append(("pdt_cds", "CDS / bond spread implied", rtg("pd_cds"), "1 year", "Market quote entered on Inputs: spread / (1 - recovery)"))
    for key, label, val, hz, note in pd_rows:
        r = db.r
        book.set(DASH, r, 1, label, "text", "label", indent=1)
        book.set(DASH, r, 2, val, "pct2", "link" if isinstance(val, K) else "formula", key=key)
        book.set(DASH, r, 3, hz, "text", "note")
        book.set(DASH, r, 4, note, "text", "note")
        db.r += 1
    pd_r1 = db.r - 1
    db.blank()
    db.text("Model verdicts", "section")
    hdr(DASH, db, ["Model", "Score", "Verdict", "Rule"])
    verdicts = [
        ("v_z", "Altman Z (1968)", alt("z", L), "score", alt("z_zone", L), "Safe > 2.99, distress < 1.81"),
        ("v_z1", "Altman Z' (1983)", alt("z1", L), "score", alt("z1_zone", L), "Safe > 2.90, distress < 1.23"),
        ("v_z2", "Altman Z'' (1995)", alt("z2", L), "score", alt("z2_zone", L), "Safe > 2.60, distress < 1.10"),
        ("v_em", "Altman EM score", alt("em", L), "score", alt("em_rating", L), "Bond rating equivalent"),
        ("v_f", "Piotroski F", prior(PIO, "f_score", L), "int", prior(PIO, "f_class", L), "Strong >= 8, weak <= 2"),
        ("v_m", "Beneish M (8 variables)", prior(BEN, "m8", L), "score", prior(BEN, "m_flag", L), "Flag above -1.78"),
        ("v_o", "Ohlson O", prior(DIST, "o_score", L), "score", prior(DIST, "o_flag", L), "Distress when probability > 50%"),
        ("v_x", "Zmijewski X", dis("x_score", L), "score", dis("x_flag", L), "Distress when probability > 50%"),
        ("v_s", "Springate S", dis("s_score", L), "score", dis("s_flag", L), "Likely failure below 0.862"),
        ("v_g", "Grover G", dis("g_score", L), "score", dis("g_flag", L), "Bankrupt zone <= -0.02, healthy >= 0.01"),
        ("v_t", "Taffler Z", dis("t_score", L), "score", dis("t_flag", L), "At risk below 0"),
        ("v_dd", "Merton naive distance to default", mer("dd_naive"), "score", IF(LT(mer("dd_naive"), 1.5), "High risk", IF(LT(mer("dd_naive"), 3), "Watch", "Comfortable")), "Standard deviations to the default point"),
        ("v_r", "Synthetic rating", rtg("coverage"), "mult", rtg("rating"), "Interest coverage (or EM score) -> rating"),
    ]
    for key, label, val, fmt, verdict, rule in verdicts:
        r = db.r
        book.set(DASH, r, 1, label, "text", "label", indent=1)
        book.set(DASH, r, 2, val, fmt, "link" if isinstance(val, K) else "formula", key=f"{key}_score")
        book.set(DASH, r, 3, verdict, "text", "link" if isinstance(verdict, K) else "formula", key=f"{key}_verdict", bold=True)
        book.set(DASH, r, 4, rule, "text", "note")
        db.r += 1
    db.blank()
    db.text(f"Key credit ratios ({labels[L]})", "section")
    hdr(DASH, db, ["Ratio", "Value", "", "Comment"])
    for key, label, val, fmt, note in [
        ("kr_tl_ta", "Total liabilities / total assets", rat("r_tl_ta", L), "pct", "Above 80% leaves a thin equity cushion"),
        ("kr_de", "Debt / equity", rat("r_de", L), "mult", "Negative when book equity is negative"),
        ("kr_nd_ebitda", "Net debt / EBITDA", rat("r_nd_ebitda", L), "mult", "Above 4x is typically high-yield territory"),
        ("kr_int_cov", "Interest coverage (EBIT / interest)", rat("r_int_cov", L), "mult", "Below 1.5x signals strain; n/a when interest is not reported"),
        ("kr_current", "Current ratio", rat("r_current", L), "mult", "Below 1.0x means current liabilities exceed current assets"),
        ("kr_quick", "Quick ratio", rat("r_quick", L), "mult", ""),
        ("kr_cfo_debt", "Cash from operations / total debt", rat("r_cfo_debt", L), "pct", "Debt repayment capacity from operations"),
        ("kr_roa", "Return on assets", rat("r_roa", L), "pct", ""),
        ("kr_roe", "Return on equity (DuPont)", dup("d_roe", L) if te_pos[L] else lift("n/a (negative equity)"), "pct", "Net margin x asset turnover x equity multiplier"),
        ("kr_runway", "Cash runway when free cash flow is negative (years)", rat("r_runway", L), "num1", "n/a when free cash flow is positive"),
        ("kr_vol", "Equity volatility (annualised)", mer("sigma_E"), "pct", "Feeds the Merton models"),
    ]:
        r = db.r
        book.set(DASH, r, 1, label, "text", "label", indent=1)
        book.set(DASH, r, 2, val, fmt, "link", key=key)
        book.set(DASH, r, 4, note, "text", "note")
        db.r += 1
    # ---- chart data block (linked) and charts ----
    cd_c0 = 20   # column T
    cd_r0 = 4
    book.set(DASH, cd_r0 - 1, cd_c0, "Chart data (linked from the model sheets)", "text", "section")
    book.set(DASH, cd_r0, cd_c0, "Fiscal year", "text", "header")
    for p in H:
        book.set(DASH, cd_r0, cd_c0 + 1 + p, labels[p], "text", "header")
    cat_years = RangeRef(DASH, cd_r0, cd_c0 + 1, cd_r0, cd_c0 + nh)
    cd_rows = [
        ("cd_z", "Altman Z", lambda p: alt("z", p), "score"), ("cd_z1", "Altman Z'", lambda p: alt("z1", p), "score"),
        ("cd_z2", "Altman Z''", lambda p: alt("z2", p), "score"), ("cd_z2_safe", "Z'' safe zone", lambda p: inp("t_z2_safe"), "score"),
        ("cd_z2_dist", "Z'' distress zone", lambda p: inp("t_z2_distress"), "score"),
        ("cd_tl_ta", "Total liabilities / total assets", lambda p: rat("r_tl_ta", p), "pct"),
        ("cd_eq_ta", "Book equity / total assets", lambda p: rat("r_equity_ta", p), "pct"),
        ("cd_current", "Current ratio", lambda p: rat("r_current", p), "mult"), ("cd_quick", "Quick ratio", lambda p: rat("r_quick", p), "mult"),
        ("cd_f", "Piotroski F-score", lambda p: pio("f_score", p) if p >= 1 else None, "int"),
        ("cd_m", "Beneish M-score", lambda p: ben("m8", p) if p >= 1 else None, "score"),
        ("cd_m_thr", "Beneish threshold", lambda p: inp("t_m_flag"), "score"),
        ("cd_o_pd", "Ohlson probability", lambda p: dis("o_pd", p) if p >= 1 else None, "pct"),
        ("cd_x_pd", "Zmijewski probability", lambda p: dis("x_pd", p), "pct"),
        ("cd_roa", "Return on assets", lambda p: rat("r_roa", p), "pct"), ("cd_cfo_debt", "CFO / total debt", lambda p: rat("r_cfo_debt", p), "pct"),
    ]
    cd_row_of: Dict[str, int] = {}
    for i, (key, label, fn, fmt) in enumerate(cd_rows):
        r = cd_r0 + 1 + i
        cd_row_of[key] = r
        book.set(DASH, r, cd_c0, label, "text", "label")
        for p in H:
            content = fn(p)
            if content is None:      # no value for this year: the cell stays empty and charts show a gap
                continue
            book.set(DASH, r, cd_c0 + 1 + p, content, fmt, "link" if isinstance(content, K) else ("input" if not isinstance(content, Expr) else "formula"), key=f"{key}_{p}")
    ms_r = cd_r0 + len(cd_rows) + 3
    book.set(DASH, ms_r - 1, cd_c0, "Merton capital structure", "text", "header")
    for i, (lab, val) in enumerate([("Market equity E", mer("E")), ("Default point F", mer("F")), ("Asset value V", mer("V"))]):
        book.set(DASH, ms_r + i, cd_c0, lab, "text", "label")
        book.set(DASH, ms_r + i, cd_c0 + 1, val, "num", "link", key=f"cd_ms_{i}")

    def yr(key: str) -> RangeRef:
        return RangeRef(DASH, cd_row_of[key], cd_c0 + 1, cd_row_of[key], cd_c0 + nh)

    chart_r0 = db.r + 2
    charts = [
        Chart("z2_trend", "line", "Altman Z'' by fiscal year with zone cut-offs", f"A{chart_r0}",
              [ChartSeries("Altman Z''", yr("cd_z2"), GREEN), ChartSeries("Safe zone (2.60)", yr("cd_z2_safe"), GREY), ChartSeries("Distress zone (1.10)", yr("cd_z2_dist"), RED)],
              cat_years, "score", "Z'' score", note="Above the grey line is the safe zone; below the red line is distress."),
        Chart("z_z1_trend", "line", "Altman Z and Z' by fiscal year", f"K{chart_r0}",
              [ChartSeries("Altman Z (market equity)", yr("cd_z"), NAVY), ChartSeries("Altman Z' (book equity)", yr("cd_z1"), BLUE)], cat_years, "score", "score"),
        Chart("pd_models", "bar", "Probability of default by model", f"A{chart_r0 + 17}",
              [ChartSeries("Probability of default", RangeRef(DASH, pd_r0, 2, pd_r1, 2), ORANGE)], RangeRef(DASH, pd_r0, 1, pd_r1, 1), "pct2", "probability", y_min=0),
        Chart("radar", "radar", "Composite sub-scores (0 = minimal, 100 = severe)", f"K{chart_r0 + 17}",
              [ChartSeries("Sub-score", RangeRef(DASH, comp_r0, 3, comp_r1, 3), RED)], RangeRef(DASH, comp_r0, 1, comp_r1, 1), "num1", y_min=0, y_max=100),
        Chart("leverage", "bar", "Leverage: total liabilities and book equity as a share of total assets", f"A{chart_r0 + 34}",
              [ChartSeries("Total liabilities / total assets", yr("cd_tl_ta"), PURPLE), ChartSeries("Book equity / total assets", yr("cd_eq_ta"), BLUE)], cat_years, "pct", "share of total assets"),
        Chart("liquidity", "line", "Liquidity: current and quick ratios", f"K{chart_r0 + 34}",
              [ChartSeries("Current ratio", yr("cd_current"), NAVY), ChartSeries("Quick ratio", yr("cd_quick"), ORANGE)], cat_years, "mult", "x"),
        Chart("piotroski", "bar", "Piotroski F-score by fiscal year (0-9)", f"A{chart_r0 + 51}",
              [ChartSeries("F-score", yr("cd_f"), GREEN)], cat_years, "int", "points", y_min=0, y_max=9),
        Chart("beneish", "line", "Beneish M-score by fiscal year", f"K{chart_r0 + 51}",
              [ChartSeries("M-score", yr("cd_m"), GOLD), ChartSeries("Manipulation threshold (-1.78)", yr("cd_m_thr"), RED)], cat_years, "score", "M-score"),
        Chart("acct_pd", "line", "Accounting-model probabilities of distress by fiscal year", f"A{chart_r0 + 68}",
              [ChartSeries("Ohlson", yr("cd_o_pd"), PURPLE), ChartSeries("Zmijewski", yr("cd_x_pd"), BLUE)], cat_years, "pct", "probability", y_min=0),
        Chart("merton_structure", "bar", f"Merton capital structure ({units})", f"K{chart_r0 + 68}",
              [ChartSeries("Value", RangeRef(DASH, ms_r, cd_c0 + 1, ms_r + 2, cd_c0 + 1), ORANGE)], RangeRef(DASH, ms_r, cd_c0, ms_r + 2, cd_c0), "num", units, y_min=0),
    ]
    db.sh.charts.extend(charts)
    book.set(DASH, chart_r0 - 1, 1, "Charts (native Excel charts linked to the cells above and to the chart data block in column T)", "text", "section")
    db.sh.col_widths = {1: 52, 2: 16, 3: 18, 4: 12, 5: 20, cd_c0: 34}
    for p in H:
        db.sh.col_widths[cd_c0 + 1 + p] = 12
    db.sh.max_row = max(db.sh.max_row, chart_r0 + 85)

    # =====================================================================
    # Data quality
    # =====================================================================
    dq = SB(book, DQ, [], labels, dates, nh)
    dq.title("Data quality and verification", f"{name} - integrity checks, source traceability and independent formula verification")
    dq.text("Integrity and reasonableness checks (live formulas)", "section")
    hdr(DQ, dq, ["Check", "Value", "Threshold", "Status", "Why it matters"])
    check_keys: List[str] = []

    def check(key: str, label: str, value: Any, fmt: str, threshold: str, cond: Expr, why: str, fail_word: str = "FLAG") -> None:
        r = dq.r
        book.set(DQ, r, 1, label, "text", "label", indent=1)
        book.set(DQ, r, 2, value, fmt, "input" if not isinstance(value, Expr) else "formula", key=key)
        book.set(DQ, r, 3, threshold, "text", "note")
        book.set(DQ, r, 4, IF(cond, "PASS", fail_word), "text", "check", key=key + "_status")
        book.set(DQ, r, 5, why, "text", "note")
        check_keys.append(key + "_status")
        dq.r += 1

    bs_abs: Expr = ABS(fin("total_assets", 0) - fin("total_liabilities", 0) - fin("total_equity", 0))
    for p in H[1:]:
        bs_abs = MAX(bs_abs, ABS(fin("total_assets", p) - fin("total_liabilities", p) - fin("total_equity", p)))
    check("chk_balance", "Balance sheet identity: max |assets - liabilities - equity| across years", bs_abs, "num2", "<= 0.1% of total assets + 0.5",
          LE(bs_abs, 0.001 * fin("total_assets", L) + 0.5),
          "The reported statements must be internally consistent before any ratio is meaningful; tiny gaps are rounding in the source.", "FAIL")
    cf_gap = ABS(fin("net_change_cash", L) - (fin("cfo", L) + fin("cfi", L) + fin("cff", L)))
    check("chk_cashflow", f"Cash flow identity: |change in cash - (CFO + CFI + CFF)| ({labels[L]})", cf_gap, "num2", "<= 5% of |CFO| + 0.5",
          LE(cf_gap, 0.05 * ABS(fin("cfo", L)) + 0.5), "Large gaps mean FX effects or missing items; small ones are rounding and currency translation.")
    ebitda_gap = ABS(fin("ebitda", L) - (fin("operating_income", L) + fin("da", L)))
    check("chk_ebitda", f"Reported EBITDA reconciles to EBIT + D&A ({labels[L]})", ebitda_gap, "num2", "<= 1% of |EBITDA| + 0.5",
          LE(ebitda_gap, 0.01 * ABS(fin("ebitda", L)) + 0.5), "Reported EBITDA may include unusual items; the models use EBIT + D&A.")
    check("chk_interest", "Interest expense reported when the company carries debt", fin("interest_expense", L), "num", "> 0 if total debt > 0",
          OR(GT(fin("interest_expense", L), 0), LE(fin("total_debt", L), 0)),
          "Without interest expense the coverage-based rating cannot be computed; the rating falls back to the Altman EM score.")
    re_reported = 0 if str(P[L].source_fields.get("retained_earnings", "")).startswith("derived") else 1
    check("chk_re", "Retained earnings reported by the source (1 = yes)", re_reported, "int", "= 1", EQ(K(DQ, "chk_re"), 1),
          "Altman's X2 is retained earnings / total assets; when unreported it is zero, which understates Z for mature companies.")
    check("chk_shares", "Shares outstanding vs diluted weighted-average shares (relative difference)",
          safe(ABS(fin("shares_outstanding", L) - fin("diluted_shares", L)) / fin("diluted_shares", L)), "pct", "<= 25%",
          LE(safe(ABS(fin("shares_outstanding", L) - fin("diluted_shares", L)) / fin("diluted_shares", L)), 0.25),
          "A large gap usually means a reverse split, a big issuance or a share-class mismatch; market capitalisation may be misstated.")
    mcap_ratio = safe(inp("market_cap") / fin("total_equity", L))
    check("chk_mcap_book", "Market capitalisation / book equity", mcap_ratio, "mult", "0.02x - 1,000x or negative equity",
          OR(LE(fin("total_equity", L), 0), AND(GE(mcap_ratio, 0.02), LE(mcap_ratio, 1000))),
          "A ratio far outside this band usually means the quoted price and the share count refer to different share classes or units.")
    age_m = _months_between(A.balance_date, ds.retrieved_at[:10])
    max_age = 9 if A.ltm else 18
    check("chk_age", f"Months since the latest balance-sheet date ({A.balance_date})", age_m, "int", f"<= {max_age}", LE(K(DQ, "chk_age"), max_age),
          "Accounting-based scores describe the balance sheet at its date; stale statements miss recent deterioration.")
    price_age = _days_between(ds.market.price_date, ds.retrieved_at[:10])
    check("chk_price_age", "Days between the price date and data retrieval", price_age, "int", "<= 7", LE(K(DQ, "chk_price_age"), 7),
          "Market-based measures need a current price.")
    check("chk_years", "Fiscal years of statements available" + (" (plus the LTM column)" if A.ltm else ""), A.n_annual, "int", ">= 3", GE(K(DQ, "chk_years"), 3),
          "Trends (Piotroski, Beneish, Ohlson change terms) need at least two periods; three or more fiscal years show a trajectory.")
    min_obs = 100 if daily else 24
    check("chk_obs", "Return observations for equity volatility", mer("n_ret"), "int", f">= {min_obs}", GE(mer("n_ret"), min_obs),
          "Volatility from a short window (recent listing or re-listing) is unreliable and drives the Merton probabilities.")
    check("chk_vol", "Equity volatility used", mer("sigma_E"), "pct", "5% - 300%", AND(GE(mer("sigma_E"), 0.05), LE(mer("sigma_E"), 3.0)),
          "Volatility outside this band usually reflects a data problem or a distressed, penny-stock situation.")
    check("chk_merton", "Merton solver check: max |implied / input - 1| for equity value and volatility", MAX(ABS(mer("chk_E")), ABS(mer("chk_vol"))), "pct4", "< 0.0001%",
          LT(MAX(ABS(mer("chk_E")), ABS(mer("chk_vol"))), 0.000001), "The workbook formulas must reproduce the market inputs from the solved asset value and volatility.", "FAIL")
    check("chk_weights", "Composite weights sum to 100%", inp("weight_total"), "pct", "= 100%", LT(ABS(inp("weight_total") - 1), 1e-9),
          "The composite score is a weighted average; the weights must sum to one.", "FAIL")
    check("chk_neg_equity", f"Book equity ({labels[L]})", fin("total_equity", L), "num", "> 0", GT(fin("total_equity", L), 0),
          "Negative equity makes ROE and debt/equity meaningless and pushes Z' and Z'' down; it is itself a distress signal.")
    check("chk_financial", "Financial-sector company (1 = yes)", 1 if financial else 0, "int", "= 0", EQ(K(DQ, "chk_financial"), 0),
          "Altman, Ohlson, Zmijewski and the other accounting models were estimated on non-financial firms; for banks and insurers use regulatory capital ratios instead.")
    gp_gap = ABS(fin("gross_profit", L) - (fin("revenue", L) - fin("cogs", L)))
    check("chk_gross", f"Gross profit reconciles to revenue - cost of revenue ({labels[L]})", gp_gap, "num2", "<= 0.5% of revenue + 0.5",
          LE(gp_gap, 0.005 * ABS(fin("revenue", L)) + 0.5), "Beneish GMI and the margin signals depend on a consistent cost of revenue.")
    ni_gap = ABS(fin("net_income", L) - (fin("pretax_income", L) - fin("tax", L)))
    check("chk_ni", f"Net income reconciles to pre-tax income - tax ({labels[L]})", ni_gap, "num2", "<= 10% of |net income| + 0.5",
          LE(ni_gap, 0.10 * ABS(fin("net_income", L)) + 0.5), "Minority interest and discontinued operations explain small gaps; large ones suggest a mapping problem.")
    cash_gap = ABS(fin("begin_cash", L) + fin("net_change_cash", L) - fin("end_cash", L))
    check("chk_cashroll", f"Cash roll-forward: beginning cash + net change = ending cash ({labels[L]})", cash_gap, "num2", "<= 0.5% of ending cash + 0.5",
          LE(cash_gap, 0.005 * ABS(fin("end_cash", L)) + 0.5),
          "A broken roll-forward means the cash-flow statement fields come from different bases; small gaps are FX effects and rounding"
          + (" across the four summed quarters." if A.ltm else "."))
    check("chk_plausible", "Plausibility: total liabilities / total assets (also requires current ratio <= 50x)", rat("r_tl_ta", L), "pct", "0% - 300%",
          AND(GE(rat("r_tl_ta", L), 0), LE(rat("r_tl_ta", L), 3), LE(rat("r_current", L), 50)),
          "Ratios outside these bounds usually mean mis-scaled or mis-mapped statement items.")
    check("chk_jumps", "Largest absolute single-period return in the volatility window", float(R.stats.get("max_abs_return", 0.0)), "pct", "<= 40%",
          LE(K(DQ, "chk_jumps"), 0.40), "A single jump (re-listing, reverse split, data glitch) inflates volatility and every Merton probability.")
    check("chk_zero_days", "Share of zero-return periods in the volatility window (illiquidity)", float(R.stats.get("zero_share", 0.0)), "pct", "<= 20%",
          LE(K(DQ, "chk_zero_days"), 0.20), "Many zero-return days understate volatility and flatter the Merton probabilities.")
    vm = R.stats.get("vol_monthly")
    if R.stats.get("source") == "daily" and vm:
        ratio = float(R.stats["vol"]) / float(vm) if vm > 0 else 1.0
        check("chk_vol_cross", "Daily-based / monthly-based equity volatility", ratio, "factor", "0.5x - 2x", AND(GE(K(DQ, "chk_vol_cross"), 0.5), LE(K(DQ, "chk_vol_cross"), 2)),
              f"The five-year monthly series gives {vm:.1%}; a large gap between the two estimates means the one-year window is unusual.")
    check("chk_converged", "Merton solver converged (1 = yes)", 1 if (sol is None or sol.converged) else 0, "int", "= 1", EQ(K(DQ, "chk_converged"), 1),
          "When the two-equation solve does not converge, rely on the naive distance to default instead of the iterated probabilities.")
    check("chk_ohlson_units", "Ohlson SIZE input: log10 of total assets in US dollars", LOG10(MAX(fin("total_assets", L) * inp("fx_to_usd") * inp("ta_scale"), 1)), "num1", ">= 6",
          GE(LOG10(MAX(fin("total_assets", L) * inp("fx_to_usd") * inp("ta_scale"), 1)), 6),
          "Ohlson's SIZE term needs total assets in dollars (about 1e6 and up); smaller units shift the O-score by 0.94 per factor of ten.")
    dq.blank()
    n_fail: Expr = IF(EQ(K(DQ, check_keys[0]), "FAIL"), 1, 0)
    n_flag: Expr = IF(EQ(K(DQ, check_keys[0]), "FLAG"), 1, 0)
    for ck in check_keys[1:]:
        n_fail = n_fail + IF(EQ(K(DQ, ck), "FAIL"), 1, 0)
        n_flag = n_flag + IF(EQ(K(DQ, ck), "FLAG"), 1, 0)
    dq.scalar("n_fail", "Integrity failures", n_fail, "int", bold=True)
    dq.scalar("n_flag", "Data / applicability flags", n_flag, "int", bold=True)
    dq.scalar("overall_status", "Overall data status",
              IF(GT(K(DQ, "n_fail"), 0), "FAIL - integrity problem", IF(GT(K(DQ, "n_flag"), 0), "REVIEW - flags raised", "PASS - all checks clear")), "text", bold=True)
    dq.blank()
    # ---- model applicability (data facts, computed in Python) ----
    src_L = P[L].source_fields
    def reported(k: str) -> bool:
        v = src_L.get(k, "")
        return bool(v) and not v.startswith("derived")
    applicability: List[Dict[str, Any]] = []
    for model, req, needs_prior, accounting in MODEL_INPUTS:
        missing = [FIELD_LABELS[k] for k in req if not reported(k)]
        if accounting and financial:
            status = "Not applicable: financial institution"
        elif needs_prior and not has_prior:
            status = "Not available: needs a prior fiscal year"
        elif missing:
            status = "Applicable with gaps: not reported, treated as zero or derived"
        else:
            status = "Applicable"
        applicability.append({"model": model, "status": status, "missing": missing})
    dq.text("Model applicability and input coverage (latest fiscal year)", "section")
    hdr(DQ, dq, ["Model", "Status", "Inputs not reported by the source"])
    for a_ in applicability:
        book.set(DQ, dq.r, 1, a_["model"], "text", "label", indent=1)
        book.set(DQ, dq.r, 2, a_["status"], "text", "flag" if not a_["status"].startswith("Applicable") or a_["missing"] else "text")
        book.set(DQ, dq.r, 3, ", ".join(a_["missing"]) if a_["missing"] else "-", "text", "note")
        dq.r += 1
    dq.blank()
    dq.text("Formula verification", "section")
    dq.scalar("verification_stamp", "Independent recalculation",
              "Pending: after writing, the FinTea service recalculates this workbook with LibreOffice Calc and compares every formula cell with its own engine.",
              "text", style="note")
    dq.blank()
    dq.text(f"Source traceability ({labels[L]}, {A.basis_label})", "section")
    hdr(DQ, dq, ["Line item", "Source field", "Derived?"])
    for _, keys in FIN_GROUPS:
        for k in keys:
            src = P[L].source_fields.get(k, "")
            book.set(DQ, dq.r, 1, FIELD_LABELS[k], "text", "label", indent=1)
            book.set(DQ, dq.r, 2, src or "not reported", "text", "note")
            book.set(DQ, dq.r, 3, "derived" if src.startswith("derived") else ("reported" if src else "missing"), "text", "note")
            dq.r += 1
    dq.blank()
    dq.text("Data notes", "section")
    dq.text(f"Source: {ds.source}; retrieved {ds.retrieved_at.replace('T', ' ').replace('Z', ' UTC')}; price as of {ds.market.price_date}; "
            f"{A.describe()}; sector: {ds.profile.sector or 'n/a'} / {ds.profile.industry or 'n/a'}.", "text", wrap=True, merge_to=5)
    dq.text("- " + A.note, "text", wrap=True, merge_to=5)
    for n_ in ds.notes:
        dq.text("- " + n_, "text", wrap=True, merge_to=5)
    dq.sh.col_widths = {1: 66, 2: 18, 3: 24, 4: 26, 5: 90}

    # =====================================================================
    # Cover
    # =====================================================================
    cv = SB(book, COVER, [], labels, dates, nh)
    cv.title("FinTea Default Risk Analysis", f"{name} ({sym})")
    cv.text("Company", "section")
    for lab, val in (("Company", name), ("Ticker", sym), ("Exchange", ds.profile.exchange or "n/a"),
                     ("Sector / industry", f"{ds.profile.sector or 'n/a'} / {ds.profile.industry or 'n/a'}"),
                     ("Reporting currency", ccy), ("Units", f"{units} (shares in millions, per-share data in {ccy})"),
                     ("Data source", ds.source), ("Data retrieved", ds.retrieved_at.replace("T", " ").replace("Z", " UTC")),
                     ("Share price as of", ds.market.price_date), ("Analysis basis", f"{A.basis_label} ({labels[L]})"),
                     ("Latest balance sheet", A.balance_date), ("Periods analysed", A.describe()), ("Report generated", generated)):
        cv.scalar(None, lab, val, "text", style="text")
    cv.blank()
    cv.text("Key outputs", "section")
    cv.scalar("cover_score", "Distress signal index (0-100, uncalibrated)", dsh("composite_score"), "num1", bold=True)
    cv.scalar("cover_grade", "Index band", dsh("composite_grade"), "text", bold=True)
    cv.scalar("cover_agreement", "Distress models signalling distress", dsh("agreement"), "int")
    cv.scalar("cover_pd", "Merton naive probability of default (1 year)", mer("pd_naive"), "pct2", bold=True)
    cv.scalar("cover_dd", "Distance to default (standard deviations)", mer("dd_naive"), "score")
    cv.scalar("cover_z2", "Altman Z''-score", alt("z2", L), "score")
    cv.scalar("cover_z2_zone", "Altman Z'' zone", alt("z2_zone", L), "text")
    cv.scalar("cover_rating", "Synthetic credit rating", rtg("rating"), "text", bold=True)
    cv.scalar("cover_spread", "Rating-implied default spread", rtg("spread"), "pct2")
    cv.scalar("cover_ohlson", "Ohlson probability of bankruptcy", prior(DIST, "o_pd", L), "pct2")
    cv.scalar("cover_f", "Piotroski F-score (0-9)", prior(PIO, "f_score", L), "int")
    cv.scalar("cover_m", "Beneish M-score signal", prior(BEN, "m_flag", L), "text")
    cv.scalar("cover_dq", "Data quality status", K(DQ, "overall_status"), "text")
    cv.blank()
    cv.text("Sheet index", "section")
    toc = {ASSESS: "Written assessment, model agreement, caveats and methodology", DASH: "Composite score, probabilities of default, verdicts, charts",
           INP: "Market inputs, model choices, every coefficient and threshold with its source, rating tables",
           FIN: "Reported statements from the source (millions) with the source field per line",
           RAT: "Liquidity, leverage, coverage, profitability, cash-flow and market-based ratios by year",
           DUP: "DuPont decomposition of return on equity (three-step and five-step) by year, with charts",
           ALT: "Altman Z, Z' and Z'' with zones, EM score and bond-rating equivalent by year",
           PIO: "Nine Piotroski signals and the F-score by year", BEN: "Eight Beneish indices, M-score and manipulation flag by year",
           DIST: "Ohlson, Zmijewski, Springate, Grover and Taffler models by year",
           MER: "Equity volatility, naive distance to default, iterated Merton solve with formula checks, price data",
           RTG: "Interest-coverage synthetic rating, default spread, historical default rates", DQ: "Integrity checks, source traceability, verification"}
    for s in SHEET_ORDER[1:]:
        r = cv.r
        book.set(COVER, r, 1, s, "text", "label", hyperlink=f"#'{s}'!A1", indent=1)
        book.set(COVER, r, 2, toc[s], "text", "note")
        cv.r += 1
    cv.blank()
    cv.text("Colour legend", "section")
    book.set(COVER, cv.r, 1, "Hard-coded input (blue on yellow) - reported data, market data, model coefficients", "text", "input"); cv.r += 1
    book.set(COVER, cv.r, 1, "Calculation (black) - formula within the sheet", "text", "formula"); cv.r += 1
    book.set(COVER, cv.r, 1, "Link (green) - pulls from another sheet", "text", "link"); cv.r += 1
    book.set(COVER, cv.r, 1, "Total / headline", "text", "total"); cv.r += 1
    cv.blank()
    cv.text("Scores are generated mechanically from public data with published academic models; they are screening tools and not a credit rating, "
            "a recommendation or investment advice.", "note")
    cv.sh.col_widths = {1: 50, 2: 80}

    for s in SHEET_ORDER:
        book.sheets[s].tab_color = TAB_COLORS[s]
    book.order = list(SHEET_ORDER)

    # ---- evaluate everything, then write the narrative --------------------
    errors = book.evaluate_all()
    from .feedback import build_risk_feedback   # local import to avoid a cycle
    feedback = build_risk_feedback(book, ds, R, L, sol.to_dict() if sol else None, financial, applicability)
    ab = SB(book, ASSESS, [], labels, dates, nh)
    ab.title("Assessment", f"{name} ({sym}) - written summary generated from the model outputs on {generated}")
    ab.scalar("a_score", "Distress signal index (0-100, uncalibrated)", dsh("composite_score"), "num1", bold=True)
    ab.scalar("a_grade", "Index band", dsh("composite_grade"), "text", bold=True)
    ab.blank()
    for sec in feedback["qualitative"]:
        ab.text(sec["title"], "section")
        for line in sec["points"]:
            ab.text("- " + line, "text", wrap=True, merge_to=6, chars_per_line=170)
        ab.blank()
    ab.text("Methodology", "section")
    for line in feedback["methodology"]:
        ab.text("- " + line, "text", wrap=True, merge_to=6, chars_per_line=170)
    ab.sh.col_widths = {1: 40, 2: 30, 3: 30, 4: 30, 5: 30, 6: 30}
    book.invalidate()
    errors = book.evaluate_all()

    def num(sheet: str, key: str, p: Optional[int] = None) -> Optional[float]:
        if not book.has(sheet, key, p):
            return None
        return book.num(sheet, key, p)

    def txt(sheet: str, key: str, p: Optional[int] = None) -> Any:
        if not book.has(sheet, key, p):
            return None
        v = book.val(sheet, key, p)
        return v if isinstance(v, str) else None

    series = {"labels": labels,
              "altman_z": [num(ALT, "z", p) for p in H], "altman_z1": [num(ALT, "z1", p) for p in H], "altman_z2": [num(ALT, "z2", p) for p in H],
              "em_score": [num(ALT, "em", p) for p in H], "piotroski": [None] + [num(PIO, "f_score", p) for p in P1],
              "beneish_m": [None] + [num(BEN, "m8", p) for p in P1], "ohlson_pd": [None] + [num(DIST, "o_pd", p) for p in P1],
              "ohlson_o": [None] + [num(DIST, "o_score", p) for p in P1], "zmijewski_pd": [num(DIST, "x_pd", p) for p in H],
              "springate": [num(DIST, "s_score", p) for p in H], "grover": [num(DIST, "g_score", p) for p in H], "taffler": [num(DIST, "t_score", p) for p in H],
              "tl_ta": [num(RAT, "r_tl_ta", p) for p in H], "equity_ta": [num(RAT, "r_equity_ta", p) for p in H], "de": [num(RAT, "r_de", p) for p in H],
              "nd_ebitda": [num(RAT, "r_nd_ebitda", p) for p in H], "int_cov": [num(RAT, "r_int_cov", p) for p in H],
              "current": [num(RAT, "r_current", p) for p in H], "quick": [num(RAT, "r_quick", p) for p in H], "roa": [num(RAT, "r_roa", p) for p in H],
              "cfo_debt": [num(RAT, "r_cfo_debt", p) for p in H], "revenue": [num(FIN, "revenue", p) for p in H], "net_income": [num(FIN, "net_income", p) for p in H],
              "total_debt": [num(FIN, "total_debt", p) for p in H], "total_equity": [num(FIN, "total_equity", p) for p in H], "cash": [num(FIN, "cash_and_sti", p) for p in H],
              "fcf": [num(RAT, "fcf", p) for p in H],
              "roe": [num(DUP, "d_roe", p) for p in H], "net_margin": [num(DUP, "d_net_margin", p) for p in H],
              "asset_turnover": [num(DUP, "d_asset_turn", p) for p in H], "equity_multiplier": [num(DUP, "d_equity_mult", p) for p in H],
              "tax_burden": [num(DUP, "d_tax_burden", p) for p in H], "interest_burden": [num(DUP, "d_int_burden", p) for p in H],
              "ebit_margin": [num(DUP, "d_ebit_margin", p) for p in H], "roa_dupont": [num(DUP, "d_roa", p) for p in H]}
    summary = {
        "company": name, "symbol": sym, "currency": ccy, "units": units, "sector": ds.profile.sector, "industry": ds.profile.industry,
        "exchange": ds.profile.exchange, "financial_sector": financial, "price": ds.market.price, "price_date": ds.market.price_date,
        "market_cap": num(INP, "market_cap"), "market_cap_usd_bn": num(INP, "market_cap_usd_bn"), "base_year": base_year, "labels": labels, "nh": nh,
        "basis": A.basis, "ltm": A.ltm, "base_label": base_label, "balance_date": A.balance_date, "n_annual": A.n_annual,
        "periods_note": A.describe(), "basis_note": A.note,
        "composite_score": num(DASH, "composite_score"), "composite_grade": txt(DASH, "composite_grade"),
        "pd_merton_naive": num(MER, "pd_naive"), "dd_naive": num(MER, "dd_naive"), "pd_merton_rn": num(MER, "pd_rn"), "pd_merton_phys": num(MER, "pd_phys"),
        "dd_rn": num(MER, "dd_rn"), "asset_value": num(MER, "V"), "asset_vol": num(MER, "sigma_V"), "equity_vol": num(MER, "sigma_E"), "mu": num(MER, "mu"),
        "default_point": num(MER, "F"), "merton_check": max(abs(num(MER, "chk_E") or 0), abs(num(MER, "chk_vol") or 0)),
        "altman_z": num(ALT, "z", L), "altman_zone": txt(ALT, "z_zone", L), "altman_z1": num(ALT, "z1", L), "altman_z1_zone": txt(ALT, "z1_zone", L),
        "altman_z2": num(ALT, "z2", L), "altman_z2_zone": txt(ALT, "z2_zone", L), "em_score": num(ALT, "em", L), "em_rating": txt(ALT, "em_rating", L),
        "piotroski": num(PIO, "f_score", L), "piotroski_class": txt(PIO, "f_class", L),
        "beneish_m": num(BEN, "m8", L), "beneish_m5": num(BEN, "m5", L), "beneish_prob": num(BEN, "m_prob", L), "beneish_flag": txt(BEN, "m_flag", L),
        "ohlson_o": num(DIST, "o_score", L), "ohlson_pd": num(DIST, "o_pd", L), "ohlson_flag": txt(DIST, "o_flag", L),
        "zmijewski_x": num(DIST, "x_score", L), "zmijewski_pd": num(DIST, "x_pd", L), "zmijewski_flag": txt(DIST, "x_flag", L),
        "springate": num(DIST, "s_score", L), "springate_flag": txt(DIST, "s_flag", L), "grover": num(DIST, "g_score", L), "grover_flag": txt(DIST, "g_flag", L),
        "taffler": num(DIST, "t_score", L), "taffler_flag": txt(DIST, "t_flag", L),
        "synthetic_rating": txt(RTG, "rating"), "rating_source": txt(RTG, "rating_source"), "rating_em": txt(RTG, "rating_em"), "rating_cov": txt(RTG, "rating_cov"),
        "interest_coverage": num(RTG, "coverage") if num(RTG, "has_interest") == 1 and num(RTG, "debt_free") != 1 else None,
        "debt_free": num(RTG, "debt_free") == 1, "default_spread": num(RTG, "spread"), "implied_cost_of_debt": num(RTG, "kd"),
        "pd_rating_1y": num(RTG, "pd_1y"), "pd_rating_5y": num(RTG, "pd_5y"),
        "tl_ta": num(RAT, "r_tl_ta", L), "debt_to_equity": num(RAT, "r_de", L), "nd_ebitda": num(RAT, "r_nd_ebitda", L), "current_ratio": num(RAT, "r_current", L),
        "quick_ratio": num(RAT, "r_quick", L), "roa": num(RAT, "r_roa", L), "cfo_debt": num(RAT, "r_cfo_debt", L), "runway_years": num(RAT, "r_runway", L),
        "sub_scores": {key: num(DASH, f"{key}_sub") for key, *_ in sig_defs}, "has_prior_year": has_prior,
        "composite_equal": num(DASH, "composite_equal"), "agreement": num(DASH, "agreement"), "agreement_n": n_vote_models,
        "pd_naive_rf": num(MER, "pd_naive_rf"), "dd_naive_rf": num(MER, "dd_naive_rf"), "expected_loss": num(MER, "expected_loss"),
        "pd_cds": num(RTG, "pd_cds"), "interest_estimated_coverage": num(RTG, "coverage_est"), "rating_on_avg_ebit": txt(RTG, "rating_avg3"),
        "liquidity_coverage_12m": num(RAT, "r_liq12", L),
        "stress": {"pd_equity_shock": num(MER, "pd_stress_equity"), "pd_vol_shock": num(MER, "pd_stress_vol"), "pd_both": num(MER, "pd_stress_both"),
                   "z2_ebit_shock": num(ALT, "z2_stress", L), "z2_ebit_zone": txt(ALT, "z2_stress_zone", L),
                   "equity_shock": R.values["stress_equity"], "vol_shock": R.values["stress_vol"], "ebit_shock": R.values["stress_ebit"]},
        "applicability": applicability,
        "dupont": {"roe": num(DUP, "d_roe", L), "roe_five_step": num(DUP, "d_roe5", L), "net_margin": num(DUP, "d_net_margin", L),
                   "asset_turnover": num(DUP, "d_asset_turn", L), "equity_multiplier": num(DUP, "d_equity_mult", L),
                   "tax_burden": num(DUP, "d_tax_burden", L), "interest_burden": num(DUP, "d_int_burden", L),
                   "ebit_margin": num(DUP, "d_ebit_margin", L), "roa": num(DUP, "d_roa", L), "leverage_effect": num(DUP, "d_leverage_effect", L),
                   "roe_change": num(DUP, "d_roe_change", L)},
        "dq_status": txt(DQ, "overall_status"), "n_fail": num(DQ, "n_fail"), "n_flag": num(DQ, "n_flag"),
        "error_cells": {k: v for k, v in errors.items() if v}, "source": ds.source, "retrieved_at": ds.retrieved_at, "series": series,
        "vol_source": R.stats.get("source"), "n_returns": num(MER, "n_ret"),
    }
    return RiskResult(book=book, dataset=ds, inputs=R, summary=summary, feedback=feedback, merton=sol.to_dict() if sol else None)


def stamp_verification(result: RiskResult, verification: Dict[str, Any]) -> None:
    """Write the LibreOffice verification outcome into the Data Quality sheet (text only; formulas are unchanged)."""
    st = verification.get("status")
    if st == "verified":
        text = (f"Verified: {verification.get('cells_checked', 0):,} formula cells were recalculated independently by {verification.get('engine', 'LibreOffice Calc')} "
                f"and every one matches FinTea's evaluation engine (largest difference {verification.get('max_abs_diff', 0):.1e}).")
    elif st == "mismatch":
        text = f"MISMATCH: {verification.get('n_mismatches', 0)} of {verification.get('cells_checked', 0):,} recalculated formula cells differ from the engine; see the application for details."
    else:
        text = f"Not independently recalculated: {verification.get('reason', 'verification skipped')}."
    r, c = result.book.lookup(DQ, "verification_stamp", None)
    result.book.set(DQ, r, c, text, "text", "note", key="verification_stamp")
    result.feedback["verification_text"] = text
