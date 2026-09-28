"""Specifications of every credit / distress model used by the default-risk analyzer.

This module is the single source of truth for coefficients, thresholds and lookup
tables. The builder writes every number here into the *Inputs* sheet as a blue
input cell (with its source), and every score formula in the workbook references
those cells, so an analyst can audit or change a coefficient in Excel and the
whole workbook recalculates.

Sources are cited per model. Verify against the original papers before relying
on the numbers for anything other than screening.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Coef:
    key: str          # cell key in the Inputs sheet
    label: str        # short label shown next to the value
    value: float
    variable: str = ""  # what it multiplies (documentation only)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    source: str
    description: str
    coefs: Tuple[Coef, ...]
    thresholds: Tuple[Coef, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Altman Z-score family
# ---------------------------------------------------------------------------
ALTMAN_Z = ModelSpec(
    key="z", name="Altman Z-score (1968, listed manufacturers)",
    source="Altman, E. I. (1968), 'Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy', Journal of Finance 23(4).",
    description="Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5; X1 = working capital / total assets, X2 = retained earnings / total assets, "
                "X3 = EBIT / total assets, X4 = market value of equity / total liabilities, X5 = sales / total assets.",
    coefs=(Coef("c_z_x1", "Z: X1 working capital / total assets", 1.2, "X1"),
           Coef("c_z_x2", "Z: X2 retained earnings / total assets", 1.4, "X2"),
           Coef("c_z_x3", "Z: X3 EBIT / total assets", 3.3, "X3"),
           Coef("c_z_x4", "Z: X4 market value of equity / total liabilities", 0.6, "X4"),
           Coef("c_z_x5", "Z: X5 sales / total assets", 1.0, "X5")),
    thresholds=(Coef("t_z_safe", "Z safe zone above", 2.99), Coef("t_z_distress", "Z distress zone below", 1.81)),
)

ALTMAN_Z1 = ModelSpec(
    key="z1", name="Altman Z'-score (1983, private firms)",
    source="Altman, E. I. (1983), Corporate Financial Distress, Wiley; re-estimated with book equity in X4.",
    description="Z' = 0.717 X1 + 0.847 X2 + 3.107 X3 + 0.420 X4 + 0.998 X5, X4 = book value of equity / total liabilities.",
    coefs=(Coef("c_z1_x1", "Z': X1 working capital / total assets", 0.717, "X1"),
           Coef("c_z1_x2", "Z': X2 retained earnings / total assets", 0.847, "X2"),
           Coef("c_z1_x3", "Z': X3 EBIT / total assets", 3.107, "X3"),
           Coef("c_z1_x4", "Z': X4 book equity / total liabilities", 0.420, "X4"),
           Coef("c_z1_x5", "Z': X5 sales / total assets", 0.998, "X5")),
    thresholds=(Coef("t_z1_safe", "Z' safe zone above", 2.90), Coef("t_z1_distress", "Z' distress zone below", 1.23)),
)

ALTMAN_Z2 = ModelSpec(
    key="z2", name="Altman Z''-score (1995, non-manufacturers and emerging markets)",
    source="Altman, Hartzell & Peck (1995), 'Emerging Markets Corporate Bonds: A Scoring System', Salomon Brothers; Altman (2005), Emerging Markets Review 6.",
    description="Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 (no sales/assets term, so it is industry-neutral; Altman's recommended variant for non-manufacturers, "
                "private firms and non-US companies). EM score = Z'' + 3.25; the bond-rating equivalent (BRE) table lists Altman's median EM scores of US bond "
                "issuers by S&P rating (1995-96 sample) used here as class floors - an unadjusted statistical look-alike, not an agency rating.",
    coefs=(Coef("c_z2_x1", "Z'': X1 working capital / total assets", 6.56, "X1"),
           Coef("c_z2_x2", "Z'': X2 retained earnings / total assets", 3.26, "X2"),
           Coef("c_z2_x3", "Z'': X3 EBIT / total assets", 6.72, "X3"),
           Coef("c_z2_x4", "Z'': X4 book equity / total liabilities", 1.05, "X4"),
           Coef("c_z2_const", "EM score constant added to Z''", 3.25, "constant")),
    thresholds=(Coef("t_z2_safe", "Z'' safe zone above", 2.60), Coef("t_z2_distress", "Z'' distress zone below", 1.10)),
)

# EM score -> US bond rating equivalent: median EM scores by S&P class, 1995-96 US bond-issuer sample (Altman 2005, Table 2; Altman 2018 Figure 15),
# applied as inclusive lower bounds (range convention). Later vintages (2006, 2013) drift by up to 0.6 points per class.
EM_RATING_TABLE: List[Tuple[float, str]] = [
    (8.15, "AAA"), (7.60, "AA+"), (7.30, "AA"), (7.00, "AA-"), (6.85, "A+"), (6.65, "A"), (6.40, "A-"),
    (6.25, "BBB+"), (5.85, "BBB"), (5.65, "BBB-"), (5.25, "BB+"), (4.95, "BB"), (4.75, "BB-"), (4.50, "B+"),
    (4.15, "B"), (3.75, "B-"), (3.20, "CCC+"), (2.50, "CCC"), (1.75, "CCC-"), (float("-inf"), "D"),
]

# ---------------------------------------------------------------------------
# Piotroski F-score
# ---------------------------------------------------------------------------
PIOTROSKI = ModelSpec(
    key="f", name="Piotroski F-score (2000)",
    source="Piotroski, J. D. (2000), 'Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers', Journal of Accounting Research 38.",
    description="Nine binary signals (profitability, leverage/liquidity/source of funds, operating efficiency); 8-9 strong, 0-1 weak. "
                "ROA and asset turnover use beginning-of-year total assets; leverage uses total debt (long-term debt including the current portion) "
                "over average total assets. Designed as a fundamental-strength screen for value stocks, not as a default predictor.",
    coefs=(),
    thresholds=(Coef("t_f_strong", "F-score strong at or above", 8), Coef("t_f_weak", "F-score weak at or below (Piotroski 2000 uses 0-1; screeners often use 0-2)", 1)),
)

# ---------------------------------------------------------------------------
# Beneish M-score
# ---------------------------------------------------------------------------
BENEISH = ModelSpec(
    key="m", name="Beneish M-score (1999) - earnings manipulation",
    source="Beneish, M. D. (1999), 'The Detection of Earnings Manipulation', Financial Analysts Journal 55(5); Beneish, Lee & Nichols (2013), FAJ 69(2).",
    description="8-variable unweighted probit: M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI. "
                "M > -1.78 flags a likely manipulator (Beneish's 20:1 cost-ratio cut-off, 3.76% probability); -2.22 is a secondary-literature convention. "
                "TATA uses the Beneish-Lee-Nichols (2013) cash-flow form (income - CFO) / total assets; DEPI uses total D&A as a proxy for depreciation. "
                "The five-variable model is Beneish's earlier specification as reported in the secondary literature.",
    coefs=(Coef("c_m_const", "M: intercept", -4.84, "constant"),
           Coef("c_m_dsri", "M: DSRI days sales in receivables index", 0.920, "DSRI"),
           Coef("c_m_gmi", "M: GMI gross margin index", 0.528, "GMI"),
           Coef("c_m_aqi", "M: AQI asset quality index", 0.404, "AQI"),
           Coef("c_m_sgi", "M: SGI sales growth index", 0.892, "SGI"),
           Coef("c_m_depi", "M: DEPI depreciation index", 0.115, "DEPI"),
           Coef("c_m_sgai", "M: SGAI SG&A index", -0.172, "SGAI"),
           Coef("c_m_tata", "M: TATA total accruals / total assets", 4.679, "TATA"),
           Coef("c_m_lvgi", "M: LVGI leverage index", -0.327, "LVGI"),
           Coef("c_m5_const", "M (5-variable): intercept", -6.065, "constant"),
           Coef("c_m5_dsri", "M (5-variable): DSRI", 0.823, "DSRI"),
           Coef("c_m5_gmi", "M (5-variable): GMI", 0.906, "GMI"),
           Coef("c_m5_aqi", "M (5-variable): AQI", 0.593, "AQI"),
           Coef("c_m5_sgi", "M (5-variable): SGI", 0.717, "SGI"),
           Coef("c_m5_depi", "M (5-variable): DEPI", 0.107, "DEPI")),
    thresholds=(Coef("t_m_flag", "M-score manipulation flag above", -1.78),),
)

# ---------------------------------------------------------------------------
# Ohlson O-score
# ---------------------------------------------------------------------------
OHLSON = ModelSpec(
    key="o", name="Ohlson O-score (1980) - one-year bankruptcy logit",
    source="Ohlson, J. A. (1980), 'Financial Ratios and the Probabilistic Prediction of Bankruptcy', Journal of Accounting Research 18(1), Model 1.",
    description="O = -1.32 - 0.407 SIZE + 6.03 TLTA - 1.43 WCTA + 0.0757 CLCA - 1.72 OENEG - 2.37 NITA - 1.83 FUTL + 0.285 INTWO - 0.521 CHIN (Model 1, one-year horizon); "
                "P(bankruptcy) = e^O / (1 + e^O). SIZE = ln(total assets in US dollars / GNP price-level index of the prior year, 1968 = 100); "
                "FUTL = funds from operations (net income + D&A) / total liabilities. Ohlson's error-minimising cut-off is a probability of 3.8% (O = -3.23).",
    coefs=(Coef("c_o_const", "O: intercept", -1.32, "constant"),
           Coef("c_o_size", "O: SIZE ln(total assets / GNP price index)", -0.407, "SIZE"),
           Coef("c_o_tlta", "O: TLTA total liabilities / total assets", 6.03, "TLTA"),
           Coef("c_o_wcta", "O: WCTA working capital / total assets", -1.43, "WCTA"),
           Coef("c_o_clca", "O: CLCA current liabilities / current assets", 0.0757, "CLCA"),
           Coef("c_o_oeneg", "O: OENEG 1 if total liabilities exceed total assets", -1.72, "OENEG"),
           Coef("c_o_nita", "O: NITA net income / total assets", -2.37, "NITA"),
           Coef("c_o_futl", "O: FUTL funds from operations / total liabilities", -1.83, "FUTL"),
           Coef("c_o_intwo", "O: INTWO 1 if net loss in both of the last two years", 0.285, "INTWO"),
           Coef("c_o_chin", "O: CHIN change in net income scaled", -0.521, "CHIN")),
    thresholds=(Coef("t_o_pd", "Ohlson distress flag when probability above (0.038 = Ohlson's optimal cut-off; 0.5 = logistic midpoint)", 0.038),),
)

# ---------------------------------------------------------------------------
# Zmijewski X-score
# ---------------------------------------------------------------------------
ZMIJEWSKI = ModelSpec(
    key="x", name="Zmijewski X-score (1984) - probit",
    source="Zmijewski, M. E. (1984), 'Methodological Issues Related to the Estimation of Financial Distress Prediction Models', Journal of Accounting Research 22 (Supplement).",
    description="X = -4.336 - 4.513 ROA + 5.679 FINL + 0.004 LIQ; ROA = net income / total assets, FINL = total liabilities / total assets, "
                "LIQ = current assets / current liabilities. P(distress) = N(X); X > 0 (probability above 50%) classifies as distressed.",
    coefs=(Coef("c_x_const", "X: intercept", -4.336, "constant"),
           Coef("c_x_roa", "X: ROA net income / total assets", -4.513, "ROA"),
           Coef("c_x_finl", "X: FINL total liabilities / total assets", 5.679, "FINL"),
           Coef("c_x_liq", "X: LIQ current assets / current liabilities", 0.004, "LIQ")),
    thresholds=(Coef("t_x_pd", "Zmijewski distress flag when probability above", 0.5),),
)

# ---------------------------------------------------------------------------
# Springate, Grover, Taffler
# ---------------------------------------------------------------------------
SPRINGATE = ModelSpec(
    key="s", name="Springate S-score (1978)",
    source="Springate, G. L. V. (1978), 'Predicting the Possibility of Failure in a Canadian Firm', MBA thesis, Simon Fraser University.",
    description="S = 1.03 A + 3.07 B + 0.66 C + 0.40 D; A = working capital / total assets, B = EBIT / total assets, "
                "C = pre-tax income / current liabilities, D = sales / total assets. S < 0.862 signals likely failure.",
    coefs=(Coef("c_s_a", "S: A working capital / total assets", 1.03, "A"),
           Coef("c_s_b", "S: B EBIT / total assets", 3.07, "B"),
           Coef("c_s_c", "S: C pre-tax income / current liabilities", 0.66, "C"),
           Coef("c_s_d", "S: D sales / total assets", 0.40, "D")),
    thresholds=(Coef("t_s_cut", "S failure flag below", 0.862),),
)

GROVER = ModelSpec(
    key="g", name="Grover G-score (2001)",
    source="Grover, J. S. (2001), 'Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy: A Service Industry Extension of Altman's Z-Score Model', PhD dissertation, Cleveland State University.",
    description="G = 1.650 X1 + 3.404 X3 - 0.016 ROA + 0.057; X1 = working capital / total assets, X3 = EBIT / total assets, ROA = net income / total assets. "
                "G <= -0.02 bankrupt, G >= 0.01 healthy, in between grey.",
    coefs=(Coef("c_g_x1", "G: X1 working capital / total assets", 1.650, "X1"),
           Coef("c_g_x3", "G: X3 EBIT / total assets", 3.404, "X3"),
           Coef("c_g_roa", "G: ROA net income / total assets", -0.016, "ROA"),
           Coef("c_g_const", "G: constant", 0.057, "constant")),
    thresholds=(Coef("t_g_bankrupt", "G bankrupt at or below", -0.02), Coef("t_g_healthy", "G healthy at or above", 0.01)),
)

TAFFLER = ModelSpec(
    key="t", name="Taffler Z-score (1983, UK listed companies)",
    source="Taffler, R. J. (1983), 'The Assessment of Company Solvency and Performance Using a Statistical Model', Accounting and Business Research 13(52); Agarwal & Taffler (2007), Accounting and Business Research 37(4).",
    description="Z = 3.20 + 12.18 X1 + 2.50 X2 - 10.68 X3 + 0.029 X4; X1 = pre-tax profit / current liabilities, X2 = current assets / total liabilities, "
                "X3 = current liabilities / total assets, X4 = no-credit interval = (quick assets - current liabilities) / daily operating costs, "
                "quick assets = current assets - inventory, daily operating costs = (sales - pre-tax profit - depreciation) / 365. Z < 0 signals the at-risk region "
                "(Agarwal & Taffler 2007). Estimated on UK listed industrials.",
    coefs=(Coef("c_t_const", "Taffler: constant", 3.20, "constant"),
           Coef("c_t_x1", "Taffler: X1 pre-tax profit / current liabilities", 12.18, "X1"),
           Coef("c_t_x2", "Taffler: X2 current assets / total liabilities", 2.50, "X2"),
           Coef("c_t_x3", "Taffler: X3 current liabilities / total assets", -10.68, "X3"),
           Coef("c_t_x4", "Taffler: X4 no-credit interval (days)", 0.029, "X4")),
    thresholds=(Coef("t_t_cut", "Taffler at-risk flag below", 0.0),),
)

# ---------------------------------------------------------------------------
# Merton / Bharath-Shumway
# ---------------------------------------------------------------------------
MERTON = ModelSpec(
    key="dd", name="Merton structural model / naive distance to default",
    source="Merton, R. C. (1974), Journal of Finance 29(2); Bharath, S. T. & Shumway, T. (2008), 'Forecasting Default with the Merton Distance to Default Model', Review of Financial Studies 21(3); Crosbie & Bohn (2003), Modeling Default Risk, Moody's KMV.",
    description="Naive DD = [ln((E + F) / F) + (mu - 0.5 sigma_V^2) T] / (sigma_V sqrt(T)) with naive sigma_D = 0.05 + 0.25 sigma_E, "
                "sigma_V = E/(E+F) sigma_E + F/(E+F) sigma_D, mu = prior-year equity return, F = short-term debt + 0.5 x long-term debt; PD = N(-DD). "
                "The iterated Merton solve finds asset value V and asset volatility from E = V N(d1) - F e^(-rT) N(d2) and sigma_E = (V/E) N(d1) sigma_V.",
    coefs=(Coef("c_dd_sd_a", "Naive debt volatility intercept", 0.05, "sigma_D = a + b sigma_E"),
           Coef("c_dd_sd_b", "Naive debt volatility slope on equity volatility", 0.25, "sigma_D = a + b sigma_E"),
           Coef("c_dd_lt_share", "Share of long-term debt in the default point", 0.5, "F = STD + share x LTD"),
           Coef("c_dd_trading_days", "Trading days per year (volatility annualisation)", 252.0, "sqrt(252)")),
)

# ---------------------------------------------------------------------------
# Synthetic rating (Damodaran) and rating-implied default rates
# ---------------------------------------------------------------------------
# (lower bound of interest coverage, rating, default spread). Descending; the last row catches everything below.
# Coverage lower bounds are inclusive (Damodaran's own lookup is an approximate-match VLOOKUP on the lower bound).
# Spreads are the January 2026 vector, identical across the large-firm and smaller/riskier-firm tables.
DAMODARAN_LARGE: List[Tuple[float, str, float]] = [
    (8.50, "AAA", 0.0040), (6.50, "AA", 0.0055), (5.50, "A+", 0.0070), (4.25, "A", 0.0078), (3.00, "A-", 0.0089),
    (2.50, "BBB", 0.0111), (2.25, "BB+", 0.0138), (2.00, "BB", 0.0184), (1.75, "B+", 0.0275), (1.50, "B", 0.0321),
    (1.25, "B-", 0.0509), (0.80, "CCC", 0.0885), (0.65, "CC", 0.1261), (0.20, "C", 0.1600), (float("-inf"), "D", 0.1900),
]
DAMODARAN_SMALL: List[Tuple[float, str, float]] = [
    (12.50, "AAA", 0.0040), (9.50, "AA", 0.0055), (7.50, "A+", 0.0070), (6.00, "A", 0.0078), (4.50, "A-", 0.0089),
    (4.00, "BBB", 0.0111), (3.50, "BB+", 0.0138), (3.00, "BB", 0.0184), (2.50, "B+", 0.0275), (2.00, "B", 0.0321),
    (1.50, "B-", 0.0509), (1.25, "CCC", 0.0885), (0.80, "CC", 0.1261), (0.50, "C", 0.1600), (float("-inf"), "D", 0.1900),
]
# Default spread for every rating notch. Damodaran publishes spreads for the coverage-table ratings only; notches without a
# published spread (AA+, AA-, BBB+, BBB-, BB-, CCC+, CCC-) are the midpoint of their neighbours.
SPREAD_BY_RATING: Dict[str, float] = {
    "AAA": 0.0040, "AA+": 0.0048, "AA": 0.0055, "AA-": 0.0063, "A+": 0.0070, "A": 0.0078, "A-": 0.0089, "BBB+": 0.0100, "BBB": 0.0111,
    "BBB-": 0.0125, "BB+": 0.0138, "BB": 0.0184, "BB-": 0.0230, "B+": 0.0275, "B": 0.0321, "B-": 0.0509, "CCC+": 0.0697, "CCC": 0.0885,
    "CCC-": 0.1073, "CC": 0.1261, "C": 0.1600, "D": 0.1900,
}
DAMODARAN_AS_OF = "January 2026"
DAMODARAN_SOURCE = ("Damodaran, A., 'Ratings, Interest Coverage Ratios and Default Spread', NYU Stern, "
                    f"pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html and pc/ratings.xls ('Data used is as of {DAMODARAN_AS_OF}'); "
                    "coverage lower bounds inclusive; the smaller/riskier-firm ranges come from the same workbook.")
LARGE_FIRM_MCAP_USD_BN = 5.0

# Rating -> average cumulative default rate (fraction) by horizon. Rating notch order is the risk ordinal used in the composite.
RATING_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
                "CCC+", "CCC", "CCC-", "CC", "C", "D"]
# S&P Global Ratings, 'Default, Transition, and Recovery: 2024 Annual Global Corporate Default And Rating Transition Study'
# (published 2025), Table 24: global corporate average cumulative default rates 1981-2024 (%). Modifier ratings use their letter class.
SP_DEFAULT_RATES: Dict[str, Dict[str, float]] = {   # rating class -> {horizon years: rate}
    "AAA": {"1": 0.0000, "5": 0.0034},
    "AA": {"1": 0.0002, "5": 0.0028},
    "A": {"1": 0.0005, "5": 0.0039},
    "BBB": {"1": 0.0014, "5": 0.0136},
    "BB": {"1": 0.0056, "5": 0.0575},
    "B": {"1": 0.0293, "5": 0.1560},
    "CCC": {"1": 0.2612, "5": 0.4653},
}
SP_HORIZONS = ("1", "5")
SP_AS_OF = "1981-2024 averages (S&P Global Ratings 2024 default study, Table 24)"
SP_SOURCE = ("S&P Global Ratings (2025), 'Default, Transition, and Recovery: 2024 Annual Global Corporate Default And Rating "
             "Transition Study', Table 24 'Global corporate average cumulative default rates (1981-2024)'.")


def rating_class(rating: str) -> str:
    """Map a notched rating (BB+, CCC-) to its letter class used in the default-rate table."""
    r = rating.rstrip("+-")
    if r in ("CC", "C"):
        return "CCC"
    return r if r in SP_DEFAULT_RATES else "CCC"


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    weight: float
    how: str   # documentation of the 0-100 mapping


COMPOSITE_SIGNALS: Tuple[Signal, ...] = (
    Signal("w_z2", "Altman Z'' (zone-scaled)", 0.20, "0 at the safe cut-off (2.60) rising linearly to 100 at the distress cut-off (1.10)."),
    Signal("w_merton", "Merton naive probability of default", 0.20, "Log scale: 0 at PD <= 0.01%, 100 at PD >= 20%."),
    Signal("w_ohlson", "Ohlson O-score", 0.15, "0 at O = -6.5 (about 0.15% probability) rising linearly to 100 at O = 0 (50%); Ohlson's 3.8% cut-off (O = -3.23) scores 50."),
    Signal("w_rating", "Synthetic rating notch", 0.15, "AAA = 0 ... D = 100, linear across the rating scale."),
    Signal("w_zmijewski", "Zmijewski X-score", 0.10, "0 at X = -3 (about 0.1% probability) rising linearly to 100 at X = 0 (50%)."),
    Signal("w_piotroski", "Piotroski F-score (inverted)", 0.10, "100 x (9 - F) / 9."),
    Signal("w_consensus", "Springate / Grover / Taffler distress flags", 0.10, "100 x (number of models flagging distress) / 3."),
)
GRADES: List[Tuple[float, str]] = [(80, "Severe"), (60, "High"), (40, "Moderate"), (20, "Low"), (float("-inf"), "Minimal")]

ALL_MODELS: List[ModelSpec] = [ALTMAN_Z, ALTMAN_Z1, ALTMAN_Z2, PIOTROSKI, BENEISH, OHLSON, ZMIJEWSKI, SPRINGATE, GROVER, TAFFLER, MERTON]

# Yahoo Finance sector / industry words that mark a company as a financial institution, for which
# accounting-ratio bankruptcy models are not designed.
FINANCIAL_WORDS = ("bank", "financ", "insur", "capital market", "reit", "real estate investment", "asset management",
                   "brokerage", "stock exchange", "lending", "mortgage", "nbfc", "credit services")


def is_financial(sector: str, industry: str = "") -> bool:
    text = f"{sector} {industry}".lower()
    return any(w in text for w in FINANCIAL_WORDS)
