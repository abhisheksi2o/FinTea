"""Fill gaps in provider data using accounting identities, recording every fix."""
from __future__ import annotations

import statistics
from typing import List

from .base import ALL_FIELDS, FinancialDataset, FiscalPeriod

SHARE_RATIO_LIMIT = 3.0   # share counts more than 3x apart cannot be the same share class or unit


def _g(p: FiscalPeriod, k: str):
    return p.fields.get(k)


def _set(p: FiscalPeriod, k: str, v: float, how: str, log: List[str]):
    p.fields[k] = v
    p.source_fields[k] = f"derived: {how}"
    log.append(f"{p.period_end[:4]}: {k} derived as {how}")


def _reconcile_share_counts(ds: FinancialDataset, log: List[str]) -> None:
    """Yahoo's shares-outstanding field is sometimes a different share class from the quoted price (Berkshire Class A
    count with the Class B quote, ASX CDIs at 10 per share) or off by a factor of 1,000 (CME, Emerald Resources), and
    single years of the diluted weighted-average series can be mis-scaled. The diluted count is reported in the same
    class as EPS and the quote, so the median of its fiscal-year series is the reference: any count more than
    SHARE_RATIO_LIMIT away from it is replaced by the nearest consistent count and the replacement is logged."""
    periods = list(ds.periods) + ([ds.ltm] if ds.ltm is not None else [])
    dil = [p.fields.get("diluted_shares") for p in ds.periods if (p.fields.get("diluted_shares") or 0) > 0]
    if not dil:
        return
    ref = float(statistics.median(dil))

    def off(v) -> bool:
        return v is None or v <= 0 or v / ref > SHARE_RATIO_LIMIT or ref / v > SHARE_RATIO_LIMIT

    for p in periods:
        f = p.fields
        d = f.get("diluted_shares")
        if d is not None and d > 0 and off(d):                      # a mis-scaled year of the diluted series
            so = f.get("shares_outstanding")
            new = so if (so and not off(so)) else ref
            _set(p, "diluted_shares", float(new), f"reported diluted shares ({d / 1e6:,.1f}m) are more than {SHARE_RATIO_LIMIT:.0f}x "
                 f"away from the {ref / 1e6:,.1f}m median of the series; replaced", log)
        so = f.get("shares_outstanding")
        if so is not None and so > 0 and off(so):                   # a different share class or unit than the diluted count
            d2 = f.get("diluted_shares")
            new = d2 if (d2 and not off(d2)) else ref
            _set(p, "shares_outstanding", float(new), f"reported shares outstanding ({so / 1e6:,.1f}m) are in a different share class "
                 f"or unit than the diluted count; replaced by {new / 1e6:,.1f}m", log)
    m = ds.market
    if m.shares_outstanding and off(m.shares_outstanding):
        last = periods[-1].fields
        new = float(last.get("shares_outstanding") or last.get("diluted_shares") or ref)
        old = m.shares_outstanding
        m.shares_outstanding = new
        ds.notes.append(f"Share count reconciled: the source's shares outstanding ({old / 1e6:,.1f}m) differ from the diluted weighted-average "
                        f"count ({ref / 1e6:,.1f}m median across the fiscal years) by more than {SHARE_RATIO_LIMIT:.0f}x, which means a different "
                        f"share class or unit; {new / 1e6:,.1f}m shares (the class of the quoted price) are used for the market capitalisation.")


def normalize(ds: FinancialDataset) -> FinancialDataset:
    log: List[str] = []
    prev: FiscalPeriod | None = None
    _reconcile_share_counts(ds, log)
    todo = list(ds.periods) + ([ds.ltm] if ds.ltm is not None else [])
    for p in todo:
        if p is ds.ltm:
            prev = ds.periods[-1] if ds.periods else None   # the LTM period follows the latest fiscal year
        for k in ALL_FIELDS:
            p.fields.setdefault(k, None)
        f = p.fields
        # income statement identities
        if f["gross_profit"] is None and f["cogs"] is not None:
            _set(p, "gross_profit", f["revenue"] - f["cogs"], "revenue - cost of revenue", log)
        if f["cogs"] is None and f["gross_profit"] is not None:
            _set(p, "cogs", f["revenue"] - f["gross_profit"], "revenue - gross profit", log)
        if f["cogs"] is None:
            _set(p, "cogs", 0.0, "not reported (zero)", log)
            f["gross_profit"] = f["revenue"]
        if f["operating_income"] is None:
            if f["ebitda"] is not None and (f["da"] or f["da_cf"]) is not None:
                _set(p, "operating_income", f["ebitda"] - (f["da"] or f["da_cf"]), "EBITDA - D&A", log)
            elif f["pretax_income"] is not None:
                _set(p, "operating_income", f["pretax_income"] + (f["interest_expense"] or 0) - (f["interest_income"] or 0),
                     "pre-tax income + interest expense - interest income", log)
            else:
                _set(p, "operating_income", 0.0, "not reported (zero)", log)
        if f["da"] is None:
            if f["da_cf"] is not None:
                _set(p, "da", f["da_cf"], "cash-flow statement D&A", log)
            elif f["ebitda"] is not None:
                _set(p, "da", f["ebitda"] - f["operating_income"], "EBITDA - EBIT", log)
            else:
                _set(p, "da", 0.0, "not reported (zero)", log)
        if f["opex_total"] is None:
            _set(p, "opex_total", f["gross_profit"] - f["operating_income"], "gross profit - operating income", log)
        if f["ebitda"] is None:
            _set(p, "ebitda", f["operating_income"] + f["da"], "EBIT + D&A", log)
        for k in ("sga", "rnd", "interest_expense", "interest_income", "tax"):
            if f[k] is None:
                _set(p, k, 0.0, "not reported (zero)", log)
        if f["net_income"] is None:
            if f["pretax_income"] is not None:
                _set(p, "net_income", f["pretax_income"] - f["tax"], "pre-tax income - tax", log)
            else:
                raise ValueError(f"net income unavailable for {p.period_end}")
        if f["pretax_income"] is None:
            _set(p, "pretax_income", f["net_income"] + f["tax"], "net income + tax", log)
        if f["diluted_shares"] is None:
            alt = f["basic_shares"] or f["shares_outstanding"]
            if alt is None:
                raise ValueError(f"share count unavailable for {p.period_end}")
            _set(p, "diluted_shares", alt, "basic shares / shares outstanding", log)
        if f["shares_outstanding"] is None:
            _set(p, "shares_outstanding", f["diluted_shares"], "diluted weighted-average shares", log)
        if f["diluted_eps"] is None:
            _set(p, "diluted_eps", f["net_income"] / f["diluted_shares"], "net income / diluted shares", log)
        # balance sheet identities
        if f["cash"] is None:
            _set(p, "cash", f["cash_and_sti"] if f["cash_and_sti"] is not None else (f["end_cash"] or 0.0),
                 "cash & short-term investments / ending cash", log)
        if f["cash_and_sti"] is None or f["cash_and_sti"] < f["cash"]:
            _set(p, "cash_and_sti", f["cash"], "cash & equivalents (no short-term investments reported)", log)
        for k in ("receivables", "inventory", "ppe", "goodwill_intangibles", "payables", "short_term_debt",
                  "long_term_debt", "retained_earnings"):
            if f[k] is None:
                _set(p, k, 0.0, "not reported (zero)", log)
        if f["current_assets"] is None:
            _set(p, "current_assets", f["cash_and_sti"] + f["receivables"] + f["inventory"], "sum of reported current assets", log)
        if f["current_liabilities"] is None:
            _set(p, "current_liabilities", f["payables"] + f["short_term_debt"], "sum of reported current liabilities", log)
        if f["total_equity"] is None and f["stockholders_equity"] is not None:
            _set(p, "total_equity", f["stockholders_equity"], "stockholders' equity", log)
        if f["total_liabilities"] is None and f["total_equity"] is not None:
            _set(p, "total_liabilities", f["total_assets"] - f["total_equity"], "total assets - total equity", log)
        if f["total_equity"] is None and f["total_liabilities"] is not None:
            _set(p, "total_equity", f["total_assets"] - f["total_liabilities"], "total assets - total liabilities", log)
        if f["total_liabilities"] is None:
            raise ValueError(f"neither total liabilities nor total equity available for {p.period_end}")
        if f["stockholders_equity"] is None:
            _set(p, "stockholders_equity", f["total_equity"], "total equity", log)
        if f["total_debt"] is None:
            _set(p, "total_debt", f["short_term_debt"] + f["long_term_debt"], "short-term + long-term debt", log)
        # cash flow identities
        for k in ("sbc", "change_wc", "dividends", "buybacks", "stock_issued", "debt_issued", "debt_repaid"):
            if f[k] is None:
                _set(p, k, 0.0, "not reported (zero)", log)
        if f["da_cf"] is None:
            _set(p, "da_cf", f["da"], "income statement D&A", log)
        if f["capex"] is None:
            _set(p, "capex", 0.0, "not reported (zero)", log)
        if f["cfo"] is None:
            _set(p, "cfo", f["net_income"] + f["da_cf"] + f["sbc"] + f["change_wc"], "NI + D&A + SBC + change in WC", log)
        if f["cfi"] is None:
            _set(p, "cfi", f["capex"], "capital expenditure", log)
        if f["cff"] is None:
            _set(p, "cff", f["dividends"] + f["buybacks"] + f["stock_issued"] + f["debt_issued"] + f["debt_repaid"],
                 "dividends + buybacks + issuance + net debt", log)
        if f["free_cash_flow"] is None:
            _set(p, "free_cash_flow", f["cfo"] + f["capex"], "CFO + capex", log)
        if f["end_cash"] is None:
            _set(p, "end_cash", f["cash"], "balance sheet cash", log)
        if f["begin_cash"] is None:
            if prev is not None and p is not ds.ltm and prev.fields.get("end_cash") is not None:
                _set(p, "begin_cash", prev.fields["end_cash"], "prior-year ending cash", log)
            else:
                _set(p, "begin_cash", f["end_cash"] - (f["net_change_cash"] or (f["cfo"] + f["cfi"] + f["cff"])),
                     "ending cash - net change", log)
        if f["net_change_cash"] is None:
            _set(p, "net_change_cash", f["end_cash"] - f["begin_cash"], "ending - beginning cash", log)
        prev = p
    if log:
        ds.notes.append("Data gaps filled from accounting identities: " + "; ".join(log[:12]) + ("; ..." if len(log) > 12 else ""))
    return ds
