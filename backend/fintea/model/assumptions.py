"""Derive default model assumptions from historical data, with an audit trail.

Every assumption has a *basis* string explaining exactly how it was derived
(which years, which formula). The basis is written next to the input in the
Assumptions sheet so a reviewer can challenge it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..providers.base import FinancialDataset

M = 1e6


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    section: str
    fmt: str            # num / pct / days / mult / price / beta / int / factor
    kind: str = "scalar"  # scalar | vector (one value per projection year)
    lo: Optional[float] = None
    hi: Optional[float] = None
    help: str = ""


ASSUMPTION_SPECS: List[Spec] = [
    # General / market
    Spec("projection_years", "Projection years", "General", "int", lo=3, hi=10, help="Number of explicit forecast years"),
    Spec("price", "Current share price", "Market data", "price", lo=0.0001),
    Spec("shares_outstanding", "Shares outstanding (millions)", "Market data", "num1", lo=0.0001),
    Spec("risk_free", "Risk-free rate", "Cost of capital", "pct2", lo=-0.02, hi=0.25),
    Spec("erp", "Equity risk premium", "Cost of capital", "pct2", lo=0.0, hi=0.20),
    Spec("size_premium", "Size / company-specific premium", "Cost of capital", "pct2", lo=-0.05, hi=0.15),
    Spec("use_blume", "Use Blume-adjusted beta (1 = yes, 0 = raw)", "Cost of capital", "int", lo=0, hi=1),
    Spec("target_debt_weight", "Target debt / (debt + equity)", "Cost of capital", "pct", lo=0.0, hi=0.95),
    Spec("cost_of_debt", "Pre-tax cost of debt", "Cost of capital", "pct2", lo=0.0, hi=0.40),
    Spec("cash_yield", "Interest yield on cash", "Operating", "pct2", lo=0.0, hi=0.25),
    Spec("tax_rate", "Effective tax rate", "Operating", "pct", lo=0.0, hi=0.60),
    Spec("dso", "Days sales outstanding (receivables)", "Working capital", "days", lo=0, hi=400),
    Spec("dio", "Days inventory outstanding", "Working capital", "days", lo=0, hi=400),
    Spec("dpo", "Days payables outstanding", "Working capital", "days", lo=0, hi=400),
    Spec("other_ca_pct", "Other current assets % of revenue", "Working capital", "pct", lo=0, hi=3),
    Spec("other_cl_pct", "Other current liabilities % of revenue", "Working capital", "pct", lo=0, hi=3),
    Spec("other_nca_pct", "Other non-current assets % of revenue", "Working capital", "pct", lo=0, hi=5),
    Spec("other_ncl_pct", "Other non-current liabilities % of revenue", "Working capital", "pct", lo=0, hi=5),
    Spec("payout_ratio", "Dividend payout ratio (% of net income)", "Capital allocation", "pct", lo=0, hi=1.5),
    Spec("share_change", "Diluted share count change p.a.", "Capital allocation", "pct2", lo=-0.15, hi=0.15),
    Spec("terminal_growth", "Terminal (perpetual) growth rate", "Terminal value", "pct2", lo=-0.02, hi=0.06),
    Spec("exit_multiple", "Exit EV / EBITDA multiple", "Terminal value", "mult", lo=1, hi=60),
    Spec("tv_method", "Terminal value method (1 = Gordon growth, 2 = exit multiple)", "Terminal value", "int", lo=1, hi=2),
    Spec("mid_year", "Mid-year discounting convention (1 = yes)", "Terminal value", "int", lo=0, hi=1),
    Spec("sbc_addback", "Add back stock-based compensation to FCFF (1 = yes)", "Terminal value", "int", lo=0, hi=1),
    # per-year drivers
    Spec("rev_growth", "Revenue growth", "Operating drivers", "pct", "vector", lo=-0.9, hi=3.0),
    Spec("gross_margin", "Gross margin", "Operating drivers", "pct", "vector", lo=-1.0, hi=1.0),
    Spec("sga_pct", "SG&A % of revenue", "Operating drivers", "pct", "vector", lo=0, hi=2),
    Spec("rnd_pct", "R&D % of revenue", "Operating drivers", "pct", "vector", lo=0, hi=2),
    Spec("other_opex_pct", "Other operating expense % of revenue", "Operating drivers", "pct", "vector", lo=-1, hi=2),
    Spec("da_pct", "D&A % of opening net PP&E", "Operating drivers", "pct", "vector", lo=0, hi=2),
    Spec("capex_pct", "Capex % of revenue", "Operating drivers", "pct", "vector", lo=0, hi=2),
    Spec("sbc_pct", "Stock-based compensation % of revenue", "Operating drivers", "pct", "vector", lo=0, hi=1),
    Spec("other_nonop", "Other non-operating income / (expense)", "Operating drivers", "num", "vector"),
    Spec("net_debt_issuance", "Net debt issuance / (repayment)", "Capital allocation", "num", "vector"),
    Spec("buybacks", "Share repurchases", "Capital allocation", "num", "vector", lo=0),
]
SPEC_BY_KEY = {s.key: s for s in ASSUMPTION_SPECS}


@dataclass
class Assumptions:
    values: Dict[str, Any] = field(default_factory=dict)   # key -> scalar or list
    basis: Dict[str, str] = field(default_factory=dict)
    overridden: List[str] = field(default_factory=list)

    @property
    def years(self) -> int:
        return int(self.values["projection_years"])

    def get(self, key: str):
        return self.values[key]

    def vec(self, key: str) -> List[float]:
        return list(self.values[key])

    def to_json(self) -> Dict[str, Any]:
        out = []
        for s in ASSUMPTION_SPECS:
            out.append({"key": s.key, "label": s.label, "section": s.section, "fmt": s.fmt, "kind": s.kind,
                        "value": self.values[s.key], "basis": self.basis.get(s.key, ""),
                        "overridden": s.key in self.overridden, "min": s.lo, "max": s.hi, "help": s.help})
        return {"years": self.years, "items": out}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _avg(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def derive_assumptions(ds: FinancialDataset, years: int = 5,
                       overrides: Optional[Dict[str, Any]] = None) -> Assumptions:
    years = int(_clamp(years, 3, 10))
    P = ds.periods
    n = len(P)
    fy = [p.fiscal_year for p in P]

    def col(key: str) -> List[float]:
        return [float(p.fields.get(key) or 0.0) / M for p in P]

    rev, cogs, sga, rnd, opex, ebit = col("revenue"), col("cogs"), col("sga"), col("rnd"), col("opex_total"), col("operating_income")
    da, capex, sbc, tax, ebt = col("da"), col("capex"), col("sbc"), col("tax"), col("pretax_income")
    ar, inv, ap, ca, cl = col("receivables"), col("inventory"), col("payables"), col("current_assets"), col("current_liabilities")
    cash, csti, ta, tl, ppe, gwi = col("cash"), col("cash_and_sti"), col("total_assets"), col("total_liabilities"), col("ppe"), col("goodwill_intangibles")
    std, ltd, ie, ii = col("short_term_debt"), col("long_term_debt"), col("interest_expense"), col("interest_income")
    div, ni, bb, si = col("dividends"), col("net_income"), col("buybacks"), col("stock_issued")
    dsh = col("diluted_shares")
    ebitda = [e + d for e, d in zip(ebit, da)]
    L = n - 1  # base year index
    recent = list(range(max(0, n - 3), n))
    yrs_txt = ", ".join(f"FY{fy[i]}" for i in recent)

    A = Assumptions()
    V, B = A.values, A.basis
    V["projection_years"] = years
    B["projection_years"] = "Explicit forecast horizon; terminal value captures cash flows beyond it."

    # ---- market ----
    V["price"] = float(ds.market.price)
    B["price"] = f"{ds.source} closing price on {ds.market.price_date} ({ds.market.currency})."
    if ds.market.fx_rate and ds.market.listing_currency and ds.market.listing_currency != ds.market.currency:
        B["price"] += (f" Quoted {ds.market.listing_price:,.2f} {ds.market.listing_currency}, converted to the reporting currency "
                       f"at {ds.market.fx_rate:,.4f}.")
    V["shares_outstanding"] = float(ds.market.shares_outstanding) / M
    B["shares_outstanding"] = f"Shares outstanding at the latest balance-sheet date (FY{fy[L]}) reported by the source."
    rf = ds.market.risk_free_rate if ds.market.risk_free_rate is not None else 0.04
    V["risk_free"] = round(float(rf), 5)
    B["risk_free"] = ds.market.risk_free_source or "Default 4.0% (source did not provide a treasury yield)."
    V["erp"] = 0.05
    B["erp"] = "Mature-market equity risk premium of 5.0% (within the 4.5-5.5% range of Damodaran / Kroll surveys)."
    V["size_premium"] = 0.0
    B["size_premium"] = "No size or company-specific premium applied by default."
    V["use_blume"] = 1
    B["use_blume"] = "Blume adjustment (0.67 x raw + 0.33) reflects mean reversion of betas toward 1.0."

    mcap = V["price"] * V["shares_outstanding"]
    debt = std[L] + ltd[L]
    dw = debt / (debt + mcap) if (debt + mcap) > 0 else 0.0
    V["target_debt_weight"] = round(dw, 4)
    B["target_debt_weight"] = (f"Current market capital structure: debt {debt:,.0f} / (debt + market cap {mcap:,.0f}) = {_pct(dw)}.")

    avg_debt = [(std[i] + ltd[i] + std[i - 1] + ltd[i - 1]) / 2 for i in range(1, n)]
    kd_obs = [ie[i] / avg_debt[i - 1] for i in range(1, n) if avg_debt[i - 1] > 0 and ie[i] > 0]
    if kd_obs:
        kd = _clamp(_avg(kd_obs[-3:]), 0.01, 0.15)
        B["cost_of_debt"] = ("Interest expense / average total debt, average of " +
                             ", ".join(f"FY{fy[i]} {_pct(kd_obs[j])}" for j, i in enumerate(range(n - len(kd_obs), n))) +
                             " (clamped to 1%-15%).")
    else:
        kd = rf + 0.015
        B["cost_of_debt"] = "No interest expense / debt history: risk-free rate + 150bp credit spread."
    V["cost_of_debt"] = round(kd, 4)

    avg_cash = [(csti[i] + csti[i - 1]) / 2 for i in range(1, n)]
    cy_obs = [ii[i] / avg_cash[i - 1] for i in range(1, n) if avg_cash[i - 1] > 0 and ii[i] > 0]
    if cy_obs:
        cy = _clamp(_avg(cy_obs[-3:]), 0.0, max(rf, 0.0))
        B["cash_yield"] = f"Interest income / average cash & short-term investments, recent average {_pct(_avg(cy_obs[-3:]))}, capped at the risk-free rate."
    else:
        cy = max(0.0, rf - 0.01)
        B["cash_yield"] = "No interest income history: risk-free rate less 100bp."
    V["cash_yield"] = round(cy, 4)

    tr_obs = [(tax[i] / ebt[i]) for i in recent if ebt[i] > 0]
    if tr_obs:
        tr = _clamp(_avg(tr_obs), 0.05, 0.35)
        B["tax_rate"] = f"Average effective tax rate (tax / pre-tax income) over {yrs_txt}: " + ", ".join(_pct(t) for t in tr_obs) + " (clamped 5%-35%)."
    else:
        tr = 0.21
        B["tax_rate"] = "Pre-tax losses in recent years: US statutory 21% assumed."
    V["tax_rate"] = round(tr, 4)

    # ---- working capital (last fiscal year) ----
    def days(num: float, den: float) -> float:
        return _clamp(365.0 * num / den, 0, 400) if den > 0 else 0.0
    V["dso"] = round(days(ar[L], rev[L]), 1)
    B["dso"] = f"FY{fy[L]}: receivables {ar[L]:,.0f} / revenue {rev[L]:,.0f} x 365."
    V["dio"] = round(days(inv[L], cogs[L]), 1)
    B["dio"] = f"FY{fy[L]}: inventory {inv[L]:,.0f} / cost of revenue {cogs[L]:,.0f} x 365."
    V["dpo"] = round(days(ap[L], cogs[L]), 1)
    B["dpo"] = f"FY{fy[L]}: payables {ap[L]:,.0f} / cost of revenue {cogs[L]:,.0f} x 365."
    oca = ca[L] - csti[L] - ar[L] - inv[L]
    ocl = cl[L] - ap[L] - std[L]
    onca = ta[L] - ca[L] - ppe[L] - gwi[L]
    oncl = tl[L] - cl[L] - ltd[L]
    for key, val, lab in (("other_ca_pct", oca, "other current assets"), ("other_cl_pct", ocl, "other current liabilities"),
                          ("other_nca_pct", onca, "other non-current assets"), ("other_ncl_pct", oncl, "other non-current liabilities")):
        pct = _clamp(val / rev[L], 0, 5) if rev[L] > 0 else 0.0
        V[key] = round(pct, 4)
        B[key] = f"FY{fy[L]}: {lab} {val:,.0f} / revenue {rev[L]:,.0f} = {_pct(pct)}, held constant."

    # ---- capital allocation ----
    po_obs = [-div[i] / ni[i] for i in recent if ni[i] > 0]
    po = _clamp(_avg(po_obs), 0, 1.0) if po_obs else 0.0
    V["payout_ratio"] = round(po, 4)
    B["payout_ratio"] = ("Average dividends paid / net income over " + yrs_txt + ": " + ", ".join(_pct(x) for x in po_obs) + ".") if po_obs else "No dividend history."
    if n >= 2 and dsh[0] > 0:
        sc = _clamp((dsh[L] / dsh[0]) ** (1 / (n - 1)) - 1, -0.05, 0.05)
        B["share_change"] = f"CAGR of diluted shares FY{fy[0]}-FY{fy[L]}: {dsh[0]:,.0f}m to {dsh[L]:,.0f}m = {_pct(sc)} p.a. (clamped +/-5%)."
    else:
        sc = 0.0
        B["share_change"] = "Insufficient history: share count held flat."
    V["share_change"] = round(sc, 4)
    bb_hist = [-(bb[i] + si[i]) for i in recent]
    bb_def = max(0.0, _avg(bb_hist))
    V["buybacks"] = [round(bb_def, 1)] * years
    B["buybacks"] = f"Average net repurchases over {yrs_txt}: " + ", ".join(f"{x:,.0f}" for x in bb_hist) + " (held flat; set to 0 to retain cash)."
    V["net_debt_issuance"] = [0.0] * years
    B["net_debt_issuance"] = "Debt held constant (maturities assumed refinanced); enter negative values to model repayment."
    V["other_nonop"] = [0.0] * years
    B["other_nonop"] = "Non-recurring / other non-operating items assumed nil in the forecast."

    # ---- terminal ----
    tg = round(min(0.025, max(rf, 0.0)), 4)
    V["terminal_growth"] = tg
    B["terminal_growth"] = "Long-run nominal growth of 2.5%, capped at the risk-free rate (a firm cannot outgrow the economy forever)."
    ev_now = mcap + debt - csti[L]
    ltm_mult = ev_now / ebitda[L] if ebitda[L] > 0 else 12.0
    V["exit_multiple"] = round(_clamp(ltm_mult, 4, 30), 1)
    B["exit_multiple"] = f"Current EV / LTM EBITDA: ({mcap:,.0f} + {debt:,.0f} - {csti[L]:,.0f}) / {ebitda[L]:,.0f} = {ltm_mult:.1f}x (clamped 4x-30x)."
    V["tv_method"] = 1
    B["tv_method"] = "Gordon growth is the primary method; the exit multiple is shown as a cross-check."
    V["mid_year"] = 1
    B["mid_year"] = "Cash flows arrive through the year, so they are discounted from mid-year."
    V["sbc_addback"] = 0
    B["sbc_addback"] = "SBC is treated as a real economic cost (not added back), per Damodaran's recommendation."

    # ---- operating drivers ----
    g_obs = [rev[i] / rev[i - 1] - 1 for i in range(1, n) if rev[i - 1] > 0]
    if len(g_obs) >= 1:
        base_i = max(0, L - 3)
        if L > 0 and rev[base_i] > 0 and rev[L] > 0:   # both endpoints positive: a real CAGR exists
            cagr = (rev[L] / rev[base_i]) ** (1 / min(3, L)) - 1
        else:                                          # negative revenue (e.g. fair-value losses): use the last observed growth
            cagr = g_obs[-1]
        start = _clamp(cagr, -0.2, 0.4)
        B["rev_growth"] = (f"Starts at the {min(3, L)}-year revenue CAGR ({_pct(cagr)}, clamped -20%..+40%) and fades linearly toward the terminal growth rate ({_pct(tg)}). "
                           f"Historical growth: " + ", ".join(f"FY{fy[i + 1]} {_pct(g)}" for i, g in enumerate(g_obs)) + ".")
    else:
        start = 0.05
        B["rev_growth"] = "Single year of history: 5% growth fading to terminal growth."
    V["rev_growth"] = [round(start + (tg - start) * j / years, 4) for j in range(years)]

    def ratio_avg(num: List[float], den: List[float], label: str, key: str, lo: float, hi: float):
        obs = [(num[i] / den[i]) for i in recent if den[i] > 0]
        val = _clamp(_avg(obs), lo, hi) if obs else 0.0
        V[key] = [round(val, 4)] * years
        B[key] = f"Average {label} over {yrs_txt}: " + ", ".join(_pct(x) for x in obs) + " (held flat)." if obs else f"No history for {label}."

    ratio_avg([r - c for r, c in zip(rev, cogs)], rev, "gross margin", "gross_margin", -1, 1)
    ratio_avg(sga, rev, "SG&A % revenue", "sga_pct", 0, 2)
    ratio_avg(rnd, rev, "R&D % revenue", "rnd_pct", 0, 2)
    other_opex = [(rev[i] - cogs[i]) - sga[i] - rnd[i] - ebit[i] for i in range(n)]
    ratio_avg(other_opex, rev, "other operating expense % revenue (incl. reconciling items)", "other_opex_pct", -1, 2)
    da_obs = [da[i] / ppe[i - 1] for i in recent if i >= 1 and ppe[i - 1] > 0]
    da_rate = _clamp(_avg(da_obs), 0.02, 1.0) if da_obs else (_clamp(da[L] / ppe[L], 0.02, 1.0) if ppe[L] > 0 else 0.1)
    V["da_pct"] = [round(da_rate, 4)] * years
    B["da_pct"] = ("Average D&A / opening net PP&E over " + ", ".join(f"FY{fy[i]} {_pct(da[i] / ppe[i - 1])}" for i in recent if i >= 1 and ppe[i - 1] > 0)
                   + " (held flat, so D&A grows with the asset base).") if da_obs else "D&A / net PP&E of the latest year."
    cx_obs = [-capex[i] / rev[i] for i in recent if rev[i] > 0]
    cx_avg = _clamp(_avg(cx_obs), 0, 2) if cx_obs else 0.0
    cx_last = _clamp(cx_obs[-1], 0, 2) if cx_obs else 0.0
    V["capex_pct"] = [round(cx_last + (cx_avg - cx_last) * j / max(years - 1, 1), 4) for j in range(years)]
    B["capex_pct"] = (f"Fades linearly from the latest year's capex / revenue ({_pct(cx_last)}) to the {len(cx_obs)}-year average ({_pct(cx_avg)}): "
                      + ", ".join(f"FY{fy[i]} {_pct(x)}" for i, x in zip(recent, cx_obs)) + ".") if cx_obs else "No capex history."
    ratio_avg(sbc, rev, "SBC % revenue", "sbc_pct", 0, 1)

    # ---- overrides ----
    if overrides:
        apply_overrides(A, overrides)
    return A


def apply_overrides(A: Assumptions, overrides: Dict[str, Any]) -> None:
    years = A.years
    if "projection_years" in overrides:
        ny = int(_clamp(float(overrides["projection_years"]), 3, 10))
        if ny != years:
            for s in ASSUMPTION_SPECS:
                if s.kind == "vector":
                    v = list(A.values[s.key])
                    A.values[s.key] = (v + [v[-1]] * ny)[:ny]
            A.values["projection_years"] = ny
            A.overridden.append("projection_years")
            years = ny
    for key, raw in overrides.items():
        if key == "projection_years" or key not in SPEC_BY_KEY:
            continue
        s = SPEC_BY_KEY[key]
        def conv(x):
            v = float(x)
            if s.lo is not None and v < s.lo:
                raise ValueError(f"{s.label}: {v} is below the minimum {s.lo}")
            if s.hi is not None and v > s.hi:
                raise ValueError(f"{s.label}: {v} is above the maximum {s.hi}")
            return int(v) if s.fmt == "int" else v
        if s.kind == "vector":
            if isinstance(raw, (list, tuple)):
                vals = [conv(x) for x in raw]
                if len(vals) < years:
                    vals = vals + [vals[-1]] * (years - len(vals)) if vals else list(A.values[key])
                A.values[key] = vals[:years]
            else:
                A.values[key] = [conv(raw)] * years
        else:
            A.values[key] = conv(raw)
        A.overridden.append(key)
        A.basis[key] = "User override. " + A.basis.get(key, "")
