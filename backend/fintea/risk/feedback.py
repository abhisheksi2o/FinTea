"""Written assessment and quantitative check extraction for the default-risk workbook."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..providers.base import FinancialDataset
from ..sheet import Book
from .inputs import RiskInputs

DASH, INP, FIN, RAT, ALT, PIO, BEN, DIST, MER, RTG, DQ = ("Dashboard", "Inputs", "Financials", "Ratios", "Altman Z", "Piotroski F",
                                                         "Beneish M", "Distress Models", "Merton PD", "Synthetic Rating", "Data Quality")


def _p(x: Any, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def _m(x: Any, d: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{d}f}x"


def _n(x: Any, d: int = 0) -> str:
    return "n/a" if x is None else f"{x:,.{d}f}"


def _s(x: Any, d: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


def build_risk_feedback(book: Book, ds: FinancialDataset, R: RiskInputs, L: int, merton: Optional[Dict[str, Any]],
                        financial: bool, applicability: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    labels = book.meta["labels"]
    ccy = ds.profile.currency
    nh = L + 1

    has_prior = nh >= 2

    def g(sheet: str, key: str, p: Optional[int] = None) -> Optional[float]:
        if not book.has(sheet, key, p):
            return None
        return book.num(sheet, key, p)

    def t(sheet: str, key: str, p: Optional[int] = None) -> str:
        if not book.has(sheet, key, p):
            return "n/a"
        v = book.val(sheet, key, p)
        return v if isinstance(v, str) else "n/a"

    # quantitative checks from the Data Quality sheet
    quantitative: List[Dict[str, Any]] = []
    sh = book.sheets[DQ]
    for (r, c), cell in sorted(sh.cells.items()):
        if c == 1 and cell.key is None and cell.style == "label":
            val_cell = sh.cells.get((r, 2))
            st_cell = sh.cells.get((r, 4))
            if val_cell is not None and st_cell is not None and st_cell.key and st_cell.key.endswith("_status"):
                v = book.value(DQ, r, 2)
                quantitative.append({"check": cell.content, "value": v if isinstance(v, (int, float)) else None, "fmt": val_cell.fmt,
                                     "threshold": sh.cells[(r, 3)].content, "status": book.value(DQ, r, 4), "why": sh.cells[(r, 5)].content})

    score, grade = g(DASH, "composite_score"), t(DASH, "composite_grade")
    pd_naive, dd_naive, pd_rn, pd_phys = g(MER, "pd_naive"), g(MER, "dd_naive"), g(MER, "pd_rn"), g(MER, "pd_phys")
    sigma_e, mu, F, E, V = g(MER, "sigma_E"), g(MER, "mu"), g(MER, "F"), g(MER, "E"), g(MER, "V")
    z, z1, z2 = g(ALT, "z", L), g(ALT, "z1", L), g(ALT, "z2", L)
    z2_first = g(ALT, "z2", 0)
    zone, zone2 = t(ALT, "z_zone", L), t(ALT, "z2_zone", L)
    em_rating = t(ALT, "em_rating", L)
    f_score, f_class = g(PIO, "f_score", L), t(PIO, "f_class", L)
    m8, m_flag, m_prob = g(BEN, "m8", L), t(BEN, "m_flag", L), g(BEN, "m_prob", L)
    o, o_pd, o_flag = g(DIST, "o_score", L), g(DIST, "o_pd", L), t(DIST, "o_flag", L)
    x, x_pd, x_flag = g(DIST, "x_score", L), g(DIST, "x_pd", L), t(DIST, "x_flag", L)
    s_flag, g_flag, t_flag = t(DIST, "s_flag", L), t(DIST, "g_flag", L), t(DIST, "t_flag", L)
    rating, rating_src, spread, kd = t(RTG, "rating"), t(RTG, "rating_source"), g(RTG, "spread"), g(RTG, "kd")
    has_int = g(RTG, "has_interest") == 1
    cov = g(RTG, "coverage") if has_int else None
    pd1, pd5 = g(RTG, "pd_1y"), g(RTG, "pd_5y")
    tl_ta, de, nd_ebitda, cur, quick = g(RAT, "r_tl_ta", L), g(RAT, "r_de", L), g(RAT, "r_nd_ebitda", L), g(RAT, "r_current", L), g(RAT, "r_quick", L)
    roa, cfo_debt, runway, fcf = g(RAT, "r_roa", L), g(RAT, "r_cfo_debt", L), g(RAT, "r_runway", L), g(RAT, "fcf", L)
    ni, rev, debt, cash, te = g(FIN, "net_income", L), g(FIN, "revenue", L), g(FIN, "total_debt", L), g(FIN, "cash_and_sti", L), g(FIN, "total_equity", L)
    mcap = g(INP, "market_cap")
    n_fail, n_flag, dq_status = g(DQ, "n_fail"), g(DQ, "n_flag"), t(DQ, "overall_status")

    distress_votes = [("Altman Z''", zone2 == "Distress"), ("Ohlson", o_flag == "Distress"), ("Zmijewski", x_flag == "Distress"),
                      ("Springate", s_flag == "Likely failure"), ("Grover", g_flag == "Bankrupt zone"), ("Taffler", t_flag == "At risk"),
                      ("Merton naive DD", dd_naive is not None and dd_naive < 1.5)]
    n_votes = sum(1 for _, v in distress_votes if v)
    flagged = [n for n, v in distress_votes if v]

    sections: List[Dict[str, Any]] = []
    pts: List[str] = []
    pts.append(f"{n_votes} of {len(distress_votes)} distress models classify {ds.profile.name} as distressed" + (f" ({', '.join(flagged)})." if flagged else ".")
               + f" The distress signal index - an uncalibrated weighted average of the model signals, not a probability - is {_n(score, 1)} out of 100 ('{grade}' band).")
    pts.append(f"Market-implied one-year probability of default (Merton naive distance to default) is {_p(pd_naive, 2)} at {_s(dd_naive)} standard deviations from the default point; "
               f"the accounting-based Ohlson and Zmijewski models put the probability at {_p(o_pd, 1)} and {_p(x_pd, 1)}, and the synthetic rating of {rating} "
               f"corresponds to a historical one-year default rate of {_p(pd1, 2)} ({_p(pd5, 1)} over five years).")
    if financial:
        pts.append("The company is a financial institution: leverage is its business model, so the accounting-ratio models (Altman, Ohlson, Zmijewski, Springate, Grover, Taffler) "
                   "systematically read as 'distressed' and should be disregarded in favour of regulatory capital, asset quality and funding metrics. The market-based Merton signal remains informative.")
    sections.append({"title": "Overall assessment", "points": pts})

    pts = []
    pts.append(f"Total liabilities are {_p(tl_ta)} of total assets and total debt is {ccy} {_n(debt)}m against {ccy} {_n(cash)}m of cash and short-term investments"
               + (f"; net debt is {_m(nd_ebitda)} EBITDA." if nd_ebitda is not None and nd_ebitda > 0 else "; the company is in a net cash position." if nd_ebitda is not None else "."))
    if te is not None and te <= 0:
        pts.append(f"Book equity is negative ({ccy} {_n(te)}m): liabilities exceed assets, which by itself is a distress signal and makes debt/equity and ROE undefined.")
    else:
        pts.append(f"Debt / equity is {_m(de)} and book equity covers {_p(g(RAT, 'r_equity_ta', L))} of total assets.")
    trend = ""
    if z2 is not None and z2_first is not None and nh >= 2:
        d = z2 - z2_first
        trend = f" It has {'improved' if d > 0.1 else 'deteriorated' if d < -0.1 else 'been stable'} from {_s(z2_first)} in {labels[0]}."
    pts.append(f"Altman Z'' of {_s(z2)} ({zone2} zone; EM-score rating equivalent {em_rating}) and Z of {_s(z)} ({zone} zone) for {labels[L]}.{trend}")
    if cfo_debt is not None and debt and debt > 0:
        pts.append(f"Cash from operations covers {_p(cfo_debt)} of total debt a year" + (f", so debt could be repaid from operations in about {_n(g(RAT, 'r_debt_cfo', L), 1)} years." if isinstance(book.val(RAT, "r_debt_cfo", L), (int, float)) else "; operating cash flow is negative, so debt cannot be serviced from operations."))
    sections.append({"title": "Solvency and leverage", "points": pts})

    pts = [f"Current ratio {_m(cur, 2)} and quick ratio {_m(quick, 2)}; working capital is {_p(g(RAT, 'r_wc_ta', L))} of total assets."]
    if fcf is not None and fcf < 0:
        pts.append(f"Free cash flow was negative ({ccy} {_n(fcf)}m in {labels[L]}); at that burn rate the cash balance lasts about {_n(runway, 1)} years without new funding.")
    else:
        pts.append(f"Free cash flow was positive ({ccy} {_n(fcf)}m in {labels[L]}), so liquidity is being replenished from operations.")
    sections.append({"title": "Liquidity", "points": pts})

    pts = [f"Return on assets of {_p(roa)} with a net margin of {_p(g(RAT, 'r_net_margin', L))} on revenue of {ccy} {_n(rev)}m."]
    if has_int:
        pts.append(f"EBIT covers interest expense {_m(cov)} times, which maps to a synthetic rating of {rating} ({rating_src}), a default spread of {_p(spread, 2)} "
                   f"and a rating-implied pre-tax cost of debt of {_p(kd, 2)}.")
    else:
        pts.append(f"The data source does not report an interest expense, so the coverage-based rating is unavailable; the synthetic rating of {rating} comes from the Altman EM score "
                   f"(spread {_p(spread, 2)}, implied cost of debt {_p(kd, 2)}). Check the filings for the actual interest charge.")
    sections.append({"title": "Profitability and coverage", "points": pts})

    pts = [f"Equity volatility of {_p(sigma_e)} ({R.stats.get('n_obs', 0)} {R.stats.get('source', '')} returns) and a trailing equity return of {_p(mu)} give a naive distance to default of "
           f"{_s(dd_naive)} standard deviations and a probability of default of {_p(pd_naive, 2)} over one year, against a default point of {ccy} {_n(F)}m and market equity of {ccy} {_n(E)}m."]
    if merton:
        pts.append(f"The iterated Merton solve gives an asset value of {ccy} {_n(V)}m with asset volatility {_p(g(MER, 'sigma_V'))}; the risk-neutral probability of default is {_p(pd_rn, 2)} "
                   f"and {_p(pd_phys, 2)} with the expected asset return. The workbook re-derives the market equity value and volatility from these solver outputs with residuals of "
                   f"{merton['residual_equity']:.1e} and {merton['residual_vol']:.1e}.")
    else:
        pts.append("There is no debt at the default point, so the structural model implies a negligible probability of default; asset value equals equity value.")
    if sigma_e is not None and sigma_e > 1.0:
        pts.append("Equity volatility above 100% is typical of distressed or penny-stock situations; the Merton probabilities are then dominated by the volatility estimate and should be read with care.")
    sections.append({"title": "Market-implied risk (Merton)", "points": pts})

    if has_prior:
        pts = [f"Piotroski F-score of {_n(f_score)} out of 9 ({f_class}) for {labels[L]} versus {labels[L - 1]}.",
               f"Beneish M-score of {_s(m8)} ({m_flag}; implied manipulation probability {_p(m_prob)}). " +
               ("An M-score above -1.78 is a warning that reported earnings may be managed; scrutinise receivables, accruals and margin changes." if m_flag == "Possible manipulation"
                else "No earnings-manipulation signal from the eight indices.")]
    else:
        pts = ["Only one fiscal year of statements is available (typical after a restructuring with fresh-start accounting or a recent listing), so the "
               "year-over-year models - Piotroski F, Beneish M and Ohlson O - cannot be computed and carry no weight in the composite."]
    if ni is not None and ni < 0:
        pts.append(f"The company reported a net loss of {ccy} {_n(-ni)}m in {labels[L]}.")
    ebit, ebt = g(FIN, "operating_income", L), g(FIN, "pretax_income", L)
    if ebit is not None and ebt is not None and ebt - ebit > 0.25 * abs(ebit) + 1:
        pts.append(f"Pre-tax income ({ccy} {_n(ebt)}m) exceeds EBIT ({ccy} {_n(ebit)}m) by a wide margin: non-operating gains (asset sales, debt extinguishment, "
                   "fair-value changes) flatter the Springate, Taffler and Ohlson terms that use pre-tax income; judge them on EBIT-based measures.")
    re_, bb, dv = g(FIN, "retained_earnings", L), g(FIN, "buybacks", L), g(FIN, "dividends", L)
    if (re_ is not None and re_ < 0 or te is not None and te <= 0) and ni is not None and ni > 0 and ((bb or 0) + (dv or 0)) < -0.5 * ni:
        pts.append("Retained earnings are negative although the company is profitable and returns more than half of its earnings through buybacks and dividends: "
                   "the deficit reflects capital returned to shareholders, not accumulated losses, yet it lowers the Altman X2 term and therefore every Z-score.")
    sections.append({"title": "Earnings quality", "points": pts})

    pts = [f"Altman Z {zone}; Z' {t(ALT, 'z1_zone', L)}; Z'' {zone2}; Ohlson {o_flag} ({_p(o_pd)}); Zmijewski {x_flag} ({_p(x_pd)}); Springate {s_flag}; "
           f"Grover {g_flag}; Taffler {t_flag}; Merton naive DD {_s(dd_naive)}; synthetic rating {rating}."]
    if n_votes == 0:
        pts.append("The models agree that default risk is low; the residual risk is in items the ratios cannot see (debt maturities, covenants, contingent liabilities).")
    elif n_votes >= 4:
        pts.append("A majority of independent models signal distress: the conclusion is robust to the choice of model.")
    else:
        pts.append("The models disagree, which is common for companies in transition (heavy investment, recent losses, or a shrinking equity base); weigh the market-implied signal and the trend.")
    sections.append({"title": "Model agreement", "points": pts})

    pts = []
    if financial:
        pts.append("Financial institution: accounting-ratio bankruptcy models are not designed for banks, insurers or REITs.")
    if ccy != "USD":
        pts.append(f"Statements are in {ccy}; the Ohlson SIZE term converts total assets to USD at the current rate and the Damodaran tables were estimated on US data.")
    if not has_int and debt and debt > 0:
        pts.append("Interest expense is not reported by the source although the company carries debt: coverage ratios are unavailable and the rating falls back to the EM score.")
    if not has_prior:
        pts.append("Single fiscal year: trend-based models are unavailable and the remaining scores rest on one balance sheet.")
    if R.stats.get("n_obs", 0) < (100 if R.stats.get("source") == "daily" else 24):
        pts.append("Short price history: the volatility estimate, and with it the Merton probabilities, is unreliable.")
    if te is not None and te <= 0:
        pts.append("Negative book equity: Z', Z'' and the leverage ratios are outside the range the models were estimated on.")
    pts.append("The accounting models were estimated on US samples from the 1960s-1990s; coefficients are not recalibrated to today's sector mix, so use them as relative signals. "
               "Default probabilities from different models are not directly comparable: Merton probabilities are market-implied, Ohlson/Zmijewski are model-fitted frequencies, "
               "and rating-based figures are long-run historical averages.")
    pts.append("Nothing here is investment advice or a credit rating; it is a mechanical screen from public data.")
    sections.append({"title": "Caveats", "points": pts})

    pts = [f"Data status: {dq_status} ({int(n_fail or 0)} failure(s), {int(n_flag or 0)} flag(s)). Source: {ds.source}; retrieved {ds.retrieved_at[:10]}; "
           f"{nh} fiscal years ({labels[0]} - {labels[L]}); price as of {ds.market.price_date}."]
    gaps = [a for a in (applicability or []) if a.get("missing")]
    if gaps:
        pts.append("Inputs not reported by the source and treated as zero or derived: " +
                   "; ".join(f"{a['model']}: {', '.join(a['missing'])}" for a in gaps) + ".")
    pts.extend(ds.notes)
    sections.append({"title": "Data quality", "points": pts})

    methodology = [
        "Altman Z (1968), Z' (1983) and Z'' (1995) discriminant scores with the published coefficients and zones; X4 uses market equity for Z and book equity for Z' and Z''. The EM score (Z'' + 3.25) is mapped to a bond-rating equivalent.",
        "Piotroski F-score: nine binary signals on profitability, leverage/liquidity/dilution and operating efficiency, year over year.",
        "Beneish M-score: eight indices comparing the year with the prior year in a probit model; the flag threshold is -1.78.",
        "Ohlson O-score (logit), Zmijewski X-score (probit), Springate, Grover and Taffler scores with published coefficients; probabilities via the logistic and standard normal functions.",
        "Merton structural model: naive distance to default per Bharath & Shumway (2008) with the KMV default point (short-term debt + half of long-term debt), and the iterated two-equation solve for asset value and volatility, cross-checked by formulas.",
        "Synthetic rating: Damodaran's interest-coverage tables (large or small firms by market capitalisation) give a rating and default spread; historical average cumulative default rates by rating class from S&P Global.",
        "Distress signal index: uncalibrated weighted average of seven sub-scores on a 0-100 scale (weights editable on the Inputs sheet, equal-weight alternative shown); "
        "it summarises model agreement and is not a probability of default. The Beneish signal is reported separately.",
        "Every number in the workbook is an Excel formula linked to the blue input cells; the workbook is recalculated independently with LibreOffice and compared cell by cell.",
    ]
    return {"status": dq_status, "n_fail": n_fail, "n_flag": n_flag, "quantitative": quantitative, "qualitative": sections, "methodology": methodology,
            "distress_votes": [{"model": n, "distress": v} for n, v in distress_votes]}
