"""Financial Modeling Prep provider (API key required: FMP_API_KEY)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

from .base import (CompanyProfile, DataProvider, FinancialDataset, FiscalPeriod, MarketSnapshot, PriceSeries,
                   ProviderError, SearchResult, align_monthly, index_for_symbol, now_iso)

BASE = "https://financialmodelingprep.com/stable"

IS_MAP = {"revenue": "revenue", "cogs": "costOfRevenue", "gross_profit": "grossProfit",
          "sga": "sellingGeneralAndAdministrativeExpenses", "rnd": "researchAndDevelopmentExpenses",
          "opex_total": "operatingExpenses", "operating_income": "operatingIncome",
          "da": "depreciationAndAmortization", "interest_expense": "interestExpense",
          "interest_income": "interestIncome", "pretax_income": "incomeBeforeTax", "tax": "incomeTaxExpense",
          "net_income": "netIncome", "diluted_shares": "weightedAverageShsOutDil",
          "basic_shares": "weightedAverageShsOut", "diluted_eps": "epsDiluted", "ebitda": "ebitda"}
BS_MAP = {"cash": "cashAndCashEquivalents", "cash_and_sti": "cashAndShortTermInvestments",
          "receivables": "netReceivables", "inventory": "inventory", "current_assets": "totalCurrentAssets",
          "ppe": "propertyPlantEquipmentNet", "goodwill_intangibles": "goodwillAndIntangibleAssets",
          "total_assets": "totalAssets", "payables": "accountPayables", "short_term_debt": "shortTermDebt",
          "current_liabilities": "totalCurrentLiabilities", "long_term_debt": "longTermDebt",
          "total_liabilities": "totalLiabilities", "total_equity": "totalEquity",
          "stockholders_equity": "totalStockholdersEquity", "retained_earnings": "retainedEarnings",
          "total_debt": "totalDebt"}
CF_MAP = {"cfo": "operatingCashFlow", "da_cf": "depreciationAndAmortization", "sbc": "stockBasedCompensation",
          "change_wc": "changeInWorkingCapital", "capex": "capitalExpenditure",
          "cfi": "netCashProvidedByInvestingActivities", "cff": "netCashProvidedByFinancingActivities",
          "dividends": "netDividendsPaid", "buybacks": "commonStockRepurchased", "stock_issued": "commonStockIssuance",
          "debt_issued": "longTermNetDebtIssuance", "begin_cash": "cashAtBeginningOfPeriod",
          "end_cash": "cashAtEndOfPeriod", "net_change_cash": "netChangeInCash", "free_cash_flow": "freeCashFlow"}


class FMPProvider(DataProvider):
    id = "fmp"
    name = "Financial Modeling Prep"
    description = "Standardised statements and prices via the FMP API."
    requires = "Environment variable FMP_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("FMP_API_KEY", "")
        self.session = requests.Session()

    def available(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        return "" if self.available() else "FMP_API_KEY is not set"

    def _get(self, path: str, **params):
        params["apikey"] = self.api_key
        r = self.session.get(f"{BASE}/{path}", params=params, timeout=30)
        if r.status_code in (401, 403):
            raise ProviderError("Financial Modeling Prep rejected the API key")
        r.raise_for_status()
        js = r.json()
        if isinstance(js, dict) and js.get("Error Message"):
            raise ProviderError(js["Error Message"])
        return js

    def search(self, query: str, limit: int = 8) -> List[SearchResult]:
        js = self._get("search-name", query=query, limit=limit)
        return [SearchResult(x["symbol"], x.get("name", ""), x.get("exchangeFullName", x.get("exchange", ""))) for x in js]

    def _monthly(self, symbol: str, name: str) -> PriceSeries:
        js = self._get("historical-price-eod/full", symbol=symbol)
        rows = js if isinstance(js, list) else js.get("historical", [])
        by_month: Dict[str, tuple] = {}
        for r in sorted(rows, key=lambda x: x["date"]):
            by_month[r["date"][:7]] = (r["date"], float(r.get("adjClose") or r["close"]))
        months = sorted(by_month)[-62:]
        today = datetime.utcnow().strftime("%Y-%m")
        months = [m for m in months if m != today][-61:]
        return PriceSeries(symbol, name, [by_month[m][0] for m in months], [by_month[m][1] for m in months])

    def fetch(self, symbol: str) -> FinancialDataset:
        prof = self._get("profile", symbol=symbol)
        if not prof:
            raise ProviderError(f"FMP has no profile for {symbol}")
        prof = prof[0]
        inc = self._get("income-statement", symbol=symbol, limit=6)
        bal = self._get("balance-sheet-statement", symbol=symbol, limit=6)
        cfs = self._get("cash-flow-statement", symbol=symbol, limit=6)
        by_date: Dict[str, FiscalPeriod] = {}

        def merge(rows, mp, tag):
            for r in rows:
                d = r["date"]
                p = by_date.setdefault(d, FiscalPeriod(period_end=d))
                for k, src in mp.items():
                    v = r.get(src)
                    if v is not None and p.fields.get(k) is None:
                        p.fields[k] = float(v)
                        p.source_fields[k] = f"{tag}.{src}"
        merge(inc, IS_MAP, "income"); merge(bal, BS_MAP, "balance"); merge(cfs, CF_MAP, "cashflow")
        periods = [by_date[d] for d in sorted(by_date) if by_date[d].fields.get("revenue") is not None][-6:]
        for p in periods:
            p.fields["shares_outstanding"] = p.fields.get("diluted_shares")
        idx_sym, idx_name = index_for_symbol(symbol)
        stock = self._monthly(symbol, prof.get("companyName", symbol))
        index = self._monthly(idx_sym, idx_name)
        stock, index = align_monthly(stock, index)
        rf = None
        try:
            t = self._get("treasury-rates")
            if t:
                rf = float(t[0]["year10"]) / 100
        except Exception:
            pass
        shares = prof.get("sharesOutstanding") or periods[-1].fields.get("diluted_shares")
        profile = CompanyProfile(symbol=symbol, name=prof.get("companyName", symbol), exchange=prof.get("exchange", ""),
                                 currency=prof.get("currency", "USD"), sector=prof.get("sector", ""),
                                 industry=prof.get("industry", ""), country=prof.get("country", ""),
                                 description=(prof.get("description") or "")[:600])
        market = MarketSnapshot(price=float(prof["price"]), price_date=now_iso()[:10], shares_outstanding=float(shares),
                                currency=prof.get("currency", "USD"), risk_free_rate=rf,
                                risk_free_source="US 10-year Treasury (FMP treasury-rates)" if rf else "",
                                index_symbol=idx_sym, index_name=idx_name)
        return FinancialDataset(profile, market, periods, stock, index, "Financial Modeling Prep", now_iso())
