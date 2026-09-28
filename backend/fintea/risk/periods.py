"""Which statement periods the default-risk analysis runs on.

The trend columns are the reported fiscal years. When the provider supplied a latest-twelve-months (LTM) period
built from quarterly statements that ends after the last fiscal year, the analysis adds it as the final column and
every "latest" measure (scores, ratios, Merton default point, rating) is computed on it; the fiscal-year basis
remains available as an option.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..providers.base import FinancialDataset, FiscalPeriod

BASES = ("ltm", "annual")
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ltm_label(period_end: str) -> str:
    """'LTM Jun-26' for a period ending 2026-06-30."""
    return f"LTM {_MON[int(period_end[5:7]) - 1]}-{period_end[2:4]}"


@dataclass
class AnalysisPeriods:
    periods: List[FiscalPeriod]
    labels: List[str]
    basis: str                       # "ltm" or "annual" (what was requested)
    ltm: bool                        # the last period is a latest-twelve-months period
    ltm_meta: Dict[str, Any] = field(default_factory=dict)
    note: str = ""                   # why the basis is what it is

    @property
    def dates(self) -> List[str]:
        return [p.period_end for p in self.periods]

    @property
    def last(self) -> FiscalPeriod:
        return self.periods[-1]

    @property
    def base_label(self) -> str:
        return self.labels[-1]

    @property
    def n_annual(self) -> int:
        return len(self.periods) - (1 if self.ltm else 0)

    @property
    def balance_date(self) -> str:
        """Date of the balance sheet the latest column uses (the LTM balance sheet can be one quarter older than its flows)."""
        if self.ltm and self.ltm_meta.get("balance_date"):
            return str(self.ltm_meta["balance_date"])
        return self.last.period_end

    @property
    def basis_label(self) -> str:
        return "latest twelve months" if self.ltm else "latest fiscal year"

    def describe(self) -> str:
        """One sentence for the workbook and the narrative: which periods the columns are."""
        fy = f"{self.n_annual} fiscal year{'s' if self.n_annual != 1 else ''} ({self.labels[0]} - {self.labels[self.n_annual - 1]})"
        if not self.ltm:
            return fy
        q = self.ltm_meta.get("quarters") or []
        span = f"four quarters {q[0][:7]} to {q[-1][:7]}" if len(q) == 4 else "four quarters"
        return f"{fy} plus {self.base_label} ({span}; balance sheet at {self.balance_date})"


def analysis_periods(ds: FinancialDataset, basis: str = "ltm") -> AnalysisPeriods:
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, got {basis!r}")
    if not ds.periods:
        raise ValueError("No annual financial statements are available for the default-risk analysis")
    annual = list(ds.periods)
    labels = [f"FY{p.fiscal_year}A" for p in annual]
    last_fy = annual[-1]
    if basis == "annual":
        note = f"Fiscal-year basis requested: the latest column is the fiscal year ended {last_fy.period_end}."
        if ds.ltm is not None and ds.ltm.period_end > last_fy.period_end:
            note += f" A latest-twelve-months period to {ds.ltm.period_end} is available with the LTM basis."
        return AnalysisPeriods(annual, labels, basis, False, dict(ds.ltm_meta or {}), note)
    if ds.ltm is None or ds.ltm.period_end <= last_fy.period_end:
        reason = (ds.ltm_meta or {}).get("reason") or "no quarterly statements were available"
        note = (f"Latest-twelve-months basis not available ({reason}); the latest column is the fiscal year ended "
                f"{last_fy.period_end}.")
        return AnalysisPeriods(annual, labels, basis, False, dict(ds.ltm_meta or {}), note)
    meta = dict(ds.ltm_meta or {})
    q = meta.get("quarters") or []
    span = f"the four quarters {q[0]} to {q[-1]}" if len(q) == 4 else "the last four quarters"
    note = (f"Latest-twelve-months basis: flows are the sum of {span}; the balance sheet is the quarter end "
            f"{meta.get('balance_date', ds.ltm.period_end)}. Year-over-year models (Piotroski, Beneish, the Ohlson change terms) compare "
            f"the LTM column with the fiscal year ended {last_fy.period_end}, so their change terms cover less than a full year of "
            f"new information.")
    return AnalysisPeriods(annual + [ds.ltm], labels + [ltm_label(ds.ltm.period_end)], basis, True, meta, note)
