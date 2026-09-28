"""Derive the market and model inputs of the default-risk workbook, each with a written basis.

Only genuinely external data and model choices are inputs here (price, shares, FX,
risk-free rate, volatility method, default-point definition, Ohlson deflator, rating
table choice, composite weights). Model coefficients and thresholds come from
``spec.py`` and are written to the Inputs sheet separately.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..providers.base import FinancialDataset, PriceSeries
from .spec import COMPOSITE_SIGNALS, LARGE_FIRM_MCAP_USD_BN, is_financial

M = 1e6


@dataclass(frozen=True)
class RSpec:
    key: str
    label: str
    section: str
    fmt: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    help: str = ""


RISK_INPUT_SPECS: List[RSpec] = [
    RSpec("price", "Current share price", "Market data", "price", lo=0.0001),
    RSpec("shares_outstanding", "Shares outstanding (millions)", "Market data", "num1", lo=0.0001),
    RSpec("fx_to_usd", "FX rate: 1 unit of reporting currency in USD", "Market data", "factor", lo=0.000001, hi=1000,
          help="Used for the USD size measures (Ohlson SIZE, large/small-firm rating table)."),
    RSpec("risk_free", "Risk-free rate (continuously compounded proxy)", "Market data", "pct2", lo=-0.02, hi=0.30),
    RSpec("horizon", "Default horizon T (years)", "Merton model", "num2", lo=0.25, hi=10),
    RSpec("equity_vol_method", "Equity volatility: 1 = computed from the price table, 2 = manual", "Merton model", "int", lo=1, hi=2),
    RSpec("equity_vol_manual", "Manual equity volatility (annualised)", "Merton model", "pct", lo=0.01, hi=5.0),
    RSpec("mu_method", "Expected asset return: 1 = prior-year equity return (Bharath-Shumway), 2 = risk-free rate, 3 = manual", "Merton model", "int", lo=1, hi=3),
    RSpec("mu_manual", "Manual expected asset return", "Merton model", "pct", lo=-0.9, hi=3.0),
    RSpec("default_point_method", "Default point F: 1 = short-term debt + 0.5 x long-term debt (KMV), 2 = total debt, 3 = total liabilities", "Merton model", "int", lo=1, hi=3),
    RSpec("gnp_index", "GNP / GDP price-level index (1968 = 100) for Ohlson SIZE", "Ohlson size variable", "num1", lo=100, hi=5000,
          help="Ohlson deflated total assets by the GNP price-level index with 1968 = 100."),
    RSpec("ta_scale", "Total assets unit multiplier for Ohlson SIZE (1,000 = USD thousands)", "Ohlson size variable", "num", lo=1, hi=1e6,
          help="Ohlson's sample reported total assets in thousands of dollars; 1,000 converts USD millions to thousands."),
    RSpec("rating_table", "Interest-coverage rating table: 1 = auto by market cap, 2 = large firms, 3 = small firms", "Synthetic rating", "int", lo=1, hi=3),
    RSpec("large_firm_threshold", "Large-firm threshold (market cap, USD billions)", "Synthetic rating", "num1", lo=0.1, hi=1000),
] + [RSpec(s.key, f"Weight: {s.label}", "Composite score weights", "pct", lo=0, hi=1, help=s.how) for s in COMPOSITE_SIGNALS]
RSPEC_BY_KEY = {s.key: s for s in RISK_INPUT_SPECS}


@dataclass
class RiskInputs:
    values: Dict[str, Any] = field(default_factory=dict)
    basis: Dict[str, str] = field(default_factory=dict)
    overridden: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)   # derived numbers used for the basis text and the summary

    def to_json(self) -> Dict[str, Any]:
        items = []
        for s in RISK_INPUT_SPECS:
            items.append({"key": s.key, "label": s.label, "section": s.section, "fmt": s.fmt, "kind": "scalar",
                          "value": self.values[s.key], "basis": self.basis.get(s.key, ""),
                          "overridden": s.key in self.overridden, "min": s.lo, "max": s.hi, "help": s.help})
        return {"items": items, "stats": self.stats}


def _log_returns(closes: List[float]) -> List[float]:
    out = []
    for a, b in zip(closes[:-1], closes[1:]):
        if a and b and a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def equity_statistics(ds: FinancialDataset) -> Dict[str, Any]:
    """Annualised equity volatility and trailing 12-month return from the best available price series."""
    daily: Optional[PriceSeries] = ds.daily_prices
    if daily is not None and len(daily.closes) >= 30:
        rets = _log_returns(daily.closes)
        n = len(rets)
        mean = sum(rets) / n
        var = sum((x - mean) ** 2 for x in rets) / (n - 1)
        vol = math.sqrt(var) * math.sqrt(252.0)
        ret12 = daily.closes[-1] / daily.closes[0] - 1.0
        return {"vol": vol, "return_12m": ret12, "n_obs": n, "source": "daily",
                "start": daily.dates[0], "end": daily.dates[-1], "annualisation": 252}
    m = ds.stock_prices
    rets = _log_returns(m.closes)
    n = len(rets)
    if n >= 2:
        mean = sum(rets) / n
        var = sum((x - mean) ** 2 for x in rets) / (n - 1)
        vol = math.sqrt(var) * math.sqrt(12.0)
    else:
        vol = 0.40
    k = min(12, len(m.closes) - 1)
    ret12 = (m.closes[-1] / m.closes[-1 - k] - 1.0) if k >= 1 and m.closes[-1 - k] > 0 else 0.0
    return {"vol": vol, "return_12m": ret12, "n_obs": n, "source": "monthly" if n >= 2 else "default",
            "start": m.dates[0] if m.dates else "", "end": m.dates[-1] if m.dates else "", "annualisation": 12}


def derive_inputs(ds: FinancialDataset, overrides: Optional[Dict[str, Any]] = None) -> RiskInputs:
    R = RiskInputs()
    V, B = R.values, R.basis
    st = equity_statistics(ds)
    R.stats.update(st)
    last = ds.periods[-1]
    fy = last.fiscal_year

    V["price"] = float(ds.market.price)
    B["price"] = f"{ds.source} closing price on {ds.market.price_date} ({ds.market.currency})."
    if ds.market.fx_rate and ds.market.listing_currency and ds.market.listing_currency != ds.market.currency:
        B["price"] += f" Quoted {ds.market.listing_price:,.2f} {ds.market.listing_currency}, converted at {ds.market.fx_rate:,.4f}."
    V["shares_outstanding"] = float(ds.market.shares_outstanding) / M
    B["shares_outstanding"] = f"Shares outstanding at the FY{fy} balance-sheet date reported by the source."
    fx = ds.market.fx_to_usd
    if fx is None:
        fx = 1.0
        B["fx_to_usd"] = ("No FX rate to USD was available: 1.0 assumed, so USD size measures are in the reporting currency. "
                          "Override with the correct rate.")
    else:
        B["fx_to_usd"] = ("Reporting currency is USD." if ds.market.currency == "USD"
                          else f"{ds.market.currency}/USD spot rate from {ds.source} at retrieval time.")
    V["fx_to_usd"] = float(fx)
    rf = ds.market.risk_free_rate if ds.market.risk_free_rate is not None else 0.04
    V["risk_free"] = round(float(rf), 5)
    B["risk_free"] = (ds.market.risk_free_source or "Default 4.0% (the source did not provide a treasury yield).") + \
        " Used as the drift in the risk-neutral Merton probability and as the base for the rating-implied cost of debt."
    V["horizon"] = 1.0
    B["horizon"] = "One-year horizon, the convention for distance-to-default and for rating agencies' one-year default rates."
    V["equity_vol_method"] = 1
    B["equity_vol_method"] = "Computed as the standard deviation of daily log returns on the Merton sheet x sqrt(252)." if st["source"] == "daily" \
        else "Daily prices unavailable: computed from monthly log returns x sqrt(12) on the Merton sheet."
    V["equity_vol_manual"] = round(st["vol"], 4)
    B["equity_vol_manual"] = (f"Defaults to the computed value {st['vol'] * 100:.1f}% ({st['n_obs']} {st['source']} returns, {st['start']} to {st['end']}). "
                              "Only used when the method is set to 2.")
    V["mu_method"] = 1
    B["mu_method"] = ("Bharath & Shumway (2008) use the firm's equity return over the previous year as the expected asset return in the naive DD; "
                      "option 2 uses the risk-free rate (risk-neutral drift).")
    V["mu_manual"] = round(st["return_12m"], 4)
    B["mu_manual"] = f"Defaults to the trailing 12-month equity return of {st['return_12m'] * 100:.1f}%; only used when the method is set to 3."
    V["default_point_method"] = 1
    B["default_point_method"] = ("Moody's KMV default point: debt due within a year plus half of long-term debt (Crosbie & Bohn 2003; Bharath & Shumway 2008). "
                                 "Total liabilities is the conservative alternative.")
    V["gnp_index"] = 640.0
    B["gnp_index"] = ("US GDP implicit price deflator, 2025 relative to 1968 = 100 (BEA NIPA Table 1.1.9: about 128.9 vs 20.1 on the 2017 = 100 base), "
                      "i.e. prices are roughly 6.4x the 1968 level. Ohlson deflated total assets by the GNP price-level index with 1968 = 100.")
    V["ta_scale"] = 1000.0
    B["ta_scale"] = ("Ohlson's Compustat sample carried total assets in thousands of US dollars, so USD millions are multiplied by 1,000 before "
                     "taking the natural log. Set to 1 to use USD millions (the SIZE term then shifts by ln(1000) x 0.407 = 2.81 points of O).")
    mcap_usd_bn = V["price"] * V["shares_outstanding"] * V["fx_to_usd"] / 1e3
    R.stats["market_cap_usd_bn"] = mcap_usd_bn
    V["rating_table"] = 1
    B["rating_table"] = (f"Auto: market capitalisation of USD {mcap_usd_bn:,.1f}bn selects the "
                         f"{'large' if mcap_usd_bn > LARGE_FIRM_MCAP_USD_BN else 'small'}-firm table (Damodaran uses USD 5bn as the split).")
    V["large_firm_threshold"] = LARGE_FIRM_MCAP_USD_BN
    B["large_firm_threshold"] = "Damodaran's split between the large-firm and small/riskier-firm coverage tables."
    financial = is_financial(ds.profile.sector, ds.profile.industry)
    R.stats["financial"] = financial
    for s in COMPOSITE_SIGNALS:
        if financial:
            V[s.key] = 1.0 if s.key == "w_merton" else 0.0
            B[s.key] = ("Financial institution: accounting-ratio models and the interest-coverage rating are not meaningful for banks and insurers, so only the "
                        "market-based Merton signal carries weight by default. " + s.how)
        else:
            V[s.key] = s.weight
            B[s.key] = s.how
    if overrides:
        apply_overrides(R, overrides)
    return R


def apply_overrides(R: RiskInputs, overrides: Dict[str, Any]) -> None:
    for key, raw in overrides.items():
        if key not in RSPEC_BY_KEY:
            continue
        s = RSPEC_BY_KEY[key]
        v = float(raw)
        if s.lo is not None and v < s.lo:
            raise ValueError(f"{s.label}: {v} is below the minimum {s.lo}")
        if s.hi is not None and v > s.hi:
            raise ValueError(f"{s.label}: {v} is above the maximum {s.hi}")
        R.values[key] = int(v) if s.fmt == "int" else v
        R.overridden.append(key)
        R.basis[key] = "User override. " + R.basis.get(key, "")
