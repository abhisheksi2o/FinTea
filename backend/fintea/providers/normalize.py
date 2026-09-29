"""Fill gaps in provider data using accounting identities, recording every fix."""
from __future__ import annotations

import math
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


def _within(a: float, b: float, limit: float = SHARE_RATIO_LIMIT) -> bool:
    return a > 0 and b > 0 and a / b <= limit and b / a <= limit


def _closer(a: float, b: float, ref: float) -> float:
    return a if abs(math.log(a / ref)) <= abs(math.log(b / ref)) else b


def _reconcile_share_counts(ds: FinancialDataset, log: List[str]) -> None:
    """Share counts from the source can be wrong by a share class or a unit: shares outstanding in another class from the
    quoted price (Berkshire Class A count with the Class B quote, ASX CDIs at 10 per share) or 1,000x off (CME, Emerald
    Resources), a diluted series summed over quarters (Digital Realty, FirstEnergy), or a whole diluted series in the
    wrong unit (Law Debenture). Genuine step changes (Brookfield Asset Management's and Sigma Healthcare's 4x issuances)
    look the same from the statements alone, so nothing is changed unless the two fields of the SAME period disagree by
    more than SHARE_RATIO_LIMIT; then the count the source's own market capitalisation implies (market cap / price, an
    independent figure) decides, or, without it, the median of the years in which the two fields agree. Finally the
    current share count is compared with the market-implied one: a gap of 1.5x or more means a split, bonus issue,
    consolidation or a large issuance after the balance-sheet date, so the market's count is used and the history is
    put on the same basis as the split-adjusted price series. Every replacement is logged."""
    periods = list(ds.periods) + ([ds.ltm] if ds.ltm is not None else [])
    m = ds.market
    ref = float(m.source_implied_shares) if (m.source_implied_shares or 0) > 0 else None
    stmt = [v for p in periods for v in (p.fields.get("shares_outstanding"), p.fields.get("diluted_shares")) if v and v > 0]
    if ref is not None and stmt and not any(_within(ref, v, 20.0) for v in stmt):
        ref = None                                                   # the source figure is not even in the same universe: ignore it
    agreed = [p.fields["shares_outstanding"] for p in periods
              if (p.fields.get("shares_outstanding") or 0) > 0 and (p.fields.get("diluted_shares") or 0) > 0
              and _within(p.fields["shares_outstanding"], p.fields["diluted_shares"])]
    anchor = ref if ref is not None else (float(statistics.median(agreed)) if agreed else None)
    for per in periods:
        f = per.fields
        so, dil = f.get("shares_outstanding"), f.get("diluted_shares")
        if not (so and dil and so > 0 and dil > 0) or _within(so, dil) or anchor is None:
            continue
        keep = _closer(so, dil, anchor)
        why = ("the count implied by the source's market capitalisation" if ref is not None else "the years in which both counts agree")
        if keep == so:
            _set(per, "diluted_shares", float(so), f"reported diluted shares ({dil / 1e6:,.1f}m) and shares outstanding ({so / 1e6:,.1f}m) are more than "
                 f"{SHARE_RATIO_LIMIT:.0f}x apart; shares outstanding kept because they match {why}", log)
        else:
            _set(per, "shares_outstanding", float(dil), f"reported shares outstanding ({so / 1e6:,.1f}m) and diluted shares ({dil / 1e6:,.1f}m) are more than "
                 f"{SHARE_RATIO_LIMIT:.0f}x apart; the diluted count kept because it matches {why}", log)
        basic = f.get("basic_shares")
        if basic and basic > 0 and not _within(basic, keep):
            _set(per, "basic_shares", float(keep), "basic shares replaced by the reconciled count", log)
    latest = periods[-1].fields
    latest_count = latest.get("shares_outstanding") or latest.get("diluted_shares")
    if m.shares_outstanding and latest_count and not _within(m.shares_outstanding, latest_count):
        old = m.shares_outstanding
        m.shares_outstanding = float(latest_count)
        ds.notes.append(f"Share count reconciled: the market share count ({old / 1e6:,.1f}m) was in a different share class or unit than the "
                        f"statements; {m.shares_outstanding / 1e6:,.1f}m shares are used for the market capitalisation.")
    if ref is not None and m.shares_outstanding and (ref / m.shares_outstanding >= 1.5 or m.shares_outstanding / ref >= 1.5):
        k = ref / m.shares_outstanding
        for per in periods:
            for key in ("shares_outstanding", "diluted_shares", "basic_shares"):
                v = per.fields.get(key)
                if v and v > 0:
                    per.fields[key] = v * k
            eps = per.fields.get("diluted_eps")
            if eps is not None:
                per.fields["diluted_eps"] = eps / k
        old = m.shares_outstanding
        m.shares_outstanding = ref
        ds.notes.append(f"Share count adjusted: the statements' latest count ({old / 1e6:,.1f}m) is {k:.2f}x away from the count implied by the source's "
                        f"market capitalisation ({ref / 1e6:,.1f}m), which points to a split, bonus issue, consolidation or large issuance after the "
                        f"balance-sheet date; the market's count is used and all share counts and per-share figures were scaled by {k:.2f} so the "
                        f"history matches the split-adjusted price series.")
        log.append(f"all periods: share counts scaled by {k:.2f} to the market's current share count")


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
