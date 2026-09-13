"""Qualitative and quantitative feedback derived from the evaluated model."""
from __future__ import annotations

from typing import Any, Dict, List

from ..providers.base import FinancialDataset
from ..sheet import Book
from .assumptions import Assumptions

IS, BS, CF, BETA, WACC, DCF, RATIOS, FEED = ("Income Statement", "Balance Sheet", "Cash Flow", "Beta", "WACC", "DCF",
                                             "Ratios", "Feedback")


def _p(x: Any, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def _m(x: Any, d: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{d}f}x"


def _n(x: Any) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def build_feedback(book: Book, ds: FinancialDataset, A: Assumptions, L: int, P: List[int]) -> Dict[str, Any]:
    nh = L + 1
    pN = P[-1]
    ccy = ds.profile.currency
    labels = book.meta["labels"]
    g = lambda s, k, p=None: book.num(s, k, p)

    rev0, revL, revN = g(IS, "revenue", 0), g(IS, "revenue", L), g(IS, "revenue", pN)
    hist_cagr = (revL / rev0) ** (1 / max(L, 1)) - 1 if rev0 and revL and rev0 > 0 and revL > 0 else None
    proj_cagr = (revN / revL) ** (1 / len(P)) - 1 if revL and revN and revL > 0 and revN > 0 else None
    gm0, gmL, gmN = g(IS, "m_gross_margin", 0), g(IS, "m_gross_margin", L), g(IS, "m_gross_margin", pN)
    em0, emL, emN = g(IS, "m_ebitda_margin", 0), g(IS, "m_ebitda_margin", L), g(IS, "m_ebitda_margin", pN)
    nm = g(IS, "m_net_margin", L)
    roe, roic = g(RATIOS, "r_roe", L), g(RATIOS, "r_roic", L)
    fcf_margin, fcf_conv = g(RATIOS, "r_fcf_margin", L), g(RATIOS, "r_fcf_conversion", L)
    nd, ebitda = g(BS, "net_debt", L), g(IS, "ebitda", L)
    nd_ebitda, int_cov = g(RATIOS, "r_nd_ebitda", L), g(RATIOS, "r_int_cov", L)
    cur = g(RATIOS, "r_current", L)
    wacc, ke = g(WACC, "wacc"), g(WACC, "cost_of_equity")
    beta_raw, beta_sel, r2, nobs = g(BETA, "raw_beta"), g(BETA, "selected_beta"), g(BETA, "r_squared"), g(BETA, "n_obs")
    implied, price, upside = g(DCF, "implied_price"), A.values["price"], g(DCF, "upside")
    tv_share, imp_mult, mkt_mult = g(DCF, "tv_share"), g(DCF, "implied_exit_multiple"), g("Assumptions", "ev_ebitda_ltm")
    z, zone = g(FEED, "altman_z"), book.val(FEED, "altman_zone")
    pio = g(FEED, "piotroski") if nh >= 2 else None
    status = book.val(FEED, "overall_status")
    n_fail, n_flag = g(FEED, "n_fail"), g(FEED, "n_flag")

    quantitative: List[Dict[str, Any]] = []
    sh = book.sheets[FEED]
    for (r, c), cell in sorted(sh.cells.items()):
        if c == 1 and cell.key is None and cell.style == "label":
            val_cell = sh.cells.get((r, 2))
            st_cell = sh.cells.get((r, 4))
            if val_cell is not None and st_cell is not None and st_cell.key and st_cell.key.endswith("_status"):
                v = book.value(FEED, r, 2)
                quantitative.append({"check": cell.content, "value": v if isinstance(v, (int, float)) else None,
                                     "fmt": val_cell.fmt, "threshold": sh.cells[(r, 3)].content,
                                     "status": book.value(FEED, r, 4), "why": sh.cells[(r, 5)].content})

    sections: List[Dict[str, Any]] = []

    # --- growth ---
    pts = []
    if hist_cagr is not None:
        pts.append(f"Revenue compounded at {_p(hist_cagr)} a year from {labels[0]} to {labels[L]} ({ccy} {_n(rev0)}m to {_n(revL)}m).")
    if proj_cagr is not None:
        tone = "faster than" if hist_cagr is not None and proj_cagr > hist_cagr + 0.02 else ("slower than" if hist_cagr is not None and proj_cagr < hist_cagr - 0.02 else "in line with")
        pts.append(f"The forecast assumes {_p(proj_cagr)} annual growth to {labels[pN]} ({ccy} {_n(revN)}m), {tone} the historical rate, "
                   f"fading toward the {_p(A.values['terminal_growth'])} terminal rate.")
    if hist_cagr is not None and hist_cagr > 0.25:
        pts.append("Growth above 25% a year is rarely sustained for five years; the fade profile in the Assumptions sheet deserves scrutiny.")
    sections.append({"title": "Growth trajectory", "points": pts})

    # --- profitability ---
    pts = []
    if gm0 is not None and gmL is not None:
        d = "expanded" if gmL > gm0 + 0.01 else ("contracted" if gmL < gm0 - 0.01 else "was stable")
        pts.append(f"Gross margin {d} from {_p(gm0)} to {_p(gmL)}; EBITDA margin moved from {_p(em0)} to {_p(emL)}.")
    if emN is not None and emL is not None:
        pts.append(f"Projected EBITDA margin in {labels[pN]} is {_p(emN)} ({'+' if emN >= emL else ''}{(emN - emL) * 100:.1f}pp vs base year), driven by the SG&A, R&D and other-opex ratios held near their recent averages.")
    if roe is not None and roic is not None:
        q = "exceptional" if roic > 0.25 else ("strong" if roic > 0.12 else ("modest" if roic > 0.06 else "weak"))
        pts.append(f"Return on invested capital of {_p(roic)} is {q} relative to the {_p(wacc, 2)} WACC; ROE is {_p(roe)}.")
    if nm is not None and nm < 0:
        pts.append("The company is loss-making at the net level; tax and interest assumptions should be reviewed for loss carry-forwards.")
    sections.append({"title": "Profitability and returns", "points": pts})

    # --- balance sheet & cash ---
    pts = []
    if nd is not None:
        if nd < 0:
            pts.append(f"Net cash position of {ccy} {_n(-nd)}m provides balance-sheet flexibility; interest income is projected on the cash balance at {_p(A.values['cash_yield'], 2)}.")
        else:
            pts.append(f"Net debt of {ccy} {_n(nd)}m equals {_m(nd_ebitda)} EBITDA; interest coverage is {_m(int_cov)}.")
    if fcf_margin is not None:
        pts.append(f"FCF margin of {_p(fcf_margin)} with {_m(fcf_conv, 2)} cash conversion of net income in {labels[L]}.")
    if cur is not None:
        pts.append(f"Current ratio of {_m(cur, 2)}. Working capital is projected from {A.values['dso']:.0f} DSO, {A.values['dio']:.0f} DIO and {A.values['dpo']:.0f} DPO.")
    if z is not None:
        pts.append(f"Altman Z-score of {z:.2f} places the company in the '{zone}' zone" + (f"; Piotroski F-score is {int(pio)}/9." if pio is not None else "."))
    sections.append({"title": "Balance sheet and cash generation", "points": pts})

    # --- valuation ---
    pts = []
    if implied is not None and upside is not None:
        view = "undervalued" if upside > 0.15 else ("overvalued" if upside < -0.15 else "fairly valued")
        pts.append(f"The DCF implies {ccy} {implied:,.2f} per share versus the market price of {ccy} {price:,.2f}, "
                   f"{'an upside' if upside >= 0 else 'a downside'} of {_p(upside)}; on these assumptions the stock screens as {view}.")
    pts.append(f"Cost of equity of {_p(ke, 2)} uses a relevered beta of {beta_sel:.2f} (raw regression beta {beta_raw:.2f}, "
               f"R-squared {r2:.2f} over {int(nobs)} monthly observations), a {_p(A.values['risk_free'], 2)} risk-free rate and a {_p(A.values['erp'], 2)} equity risk premium; WACC is {_p(wacc, 2)}.")
    if tv_share is not None:
        pts.append(f"Terminal value is {_p(tv_share)} of enterprise value. The Gordon growth terminal value implies an exit multiple of {_m(imp_mult)} EBITDA "
                   f"versus the current market multiple of {_m(mkt_mult)}.")
    mcap_book = g(FEED, "chk_mcap_book")
    if mcap_book is not None and (mcap_book > 1000 or (0 < mcap_book < 0.02)):
        pts.append("Market capitalisation is implausible relative to book equity: the quoted price and the reported share count probably "
                   "refer to different share classes or units, so the per-share value is not comparable to the price. Override "
                   "'Shares outstanding' with the count matching the quoted share class.")
    if implied is not None and implied <= 0:
        pts.append("The implied equity value is negative: on these assumptions the projected unlevered cash flows do not cover net debt. "
                   "A mechanical DCF is not meaningful here; a turnaround scenario, a sum-of-the-parts or a multiples approach is needed.")
    if g(BETA, "beta_fallback") == 1:
        pts.append(f"The regression beta ({beta_raw:.2f} over {int(nobs)} observations) is not usable, so the cost of equity uses a market beta of 1.0; "
                   "consider a bottom-up industry beta.")
    if r2 is not None and r2 < 0.1:
        pts.append("The regression beta has low explanatory power; a bottom-up industry beta would be a sensible cross-check.")
    if upside is not None and abs(upside) > 0.5:
        pts.append("The gap to the market price exceeds 50%: before concluding the market is wrong, revisit revenue growth, margins and the terminal assumptions.")
    sections.append({"title": "Valuation view", "points": pts})

    # --- risks ---
    pts = []
    if mkt_mult is not None and mkt_mult > 25:
        pts.append(f"The market already capitalises the business at {_m(mkt_mult)} EBITDA, so the valuation is sensitive to any growth disappointment.")
    if A.values["capex_pct"][-1] < A.values["da_pct"][-1]:
        pts.append("Capex is below D&A in the terminal year; steady-state reinvestment may be understated, flattering free cash flow.")
    if nd_ebitda is not None and nd_ebitda > 3:
        pts.append("Leverage above 3x EBITDA raises refinancing risk; the cost of debt assumption should include a credit spread consistent with the rating.")
    if any(w in f"{ds.profile.sector} {ds.profile.industry}".lower() for w in ("bank", "financ", "insur", "reit")):
        pts.append(f"Sector '{ds.profile.sector or ds.profile.industry}' is financial: interest-bearing liabilities are part of operations, so an "
                   "FCFF DCF overstates or understates value; prefer a dividend-discount, excess-return or P/B-based approach.")
    if ds.profile.currency != "USD":
        pts.append("Statements are in a non-USD currency while the risk-free rate is the US 10-year yield; align the risk-free rate to the currency of the cash flows.")
    if n_flag:
        pts.append(f"{int(n_flag)} assumption check(s) are flagged in the quantitative table above; each names the assumption to revisit.")
    if not pts:
        pts.append("No structural red flags were raised by the quantitative checks; the main risks are execution against the growth path and margin sustainability.")
    sections.append({"title": "Key risks and watch items", "points": pts})

    # --- data quality ---
    pts = [f"Source: {ds.source}; data retrieved {ds.retrieved_at[:10]}; {nh} historical fiscal years ({labels[0]}-{labels[L]}); price as of {ds.market.price_date}."]
    pts.extend(ds.notes)
    sections.append({"title": "Data quality", "points": pts})

    methodology = [
        "Three-statement model: revenue drives the P&L via margin ratios; working capital via DSO/DIO/DPO; PP&E via capex less D&A; equity rolls forward with net income, dividends, buybacks and SBC. The cash flow statement determines cash, so the balance sheet balances by construction.",
        "Interest is calculated on opening balances to avoid circular references.",
        "Beta: 5 years of monthly total returns regressed against the benchmark index (SLOPE), Blume-adjusted, unlevered at the current market D/E and relevered at the target structure.",
        "WACC: CAPM cost of equity (Rf + beta x ERP) and after-tax cost of debt weighted by the target capital structure.",
        "DCF: unlevered free cash flow (NOPAT + D&A - capex - change in working capital), mid-year discounting, terminal value by Gordon growth (primary) and exit multiple (cross-check); equity value = EV - debt + cash & short-term investments.",
        "Every projected figure in the workbook is an Excel formula linked to the Assumptions sheet; blue cells are the only hard-coded inputs.",
    ]
    return {"status": status, "n_fail": n_fail, "n_flag": n_flag, "quantitative": quantitative,
            "qualitative": sections, "methodology": methodology}
