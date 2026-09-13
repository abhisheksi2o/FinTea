"""Alpha Vantage provider (API key required: ALPHAVANTAGE_API_KEY). Free tier: 25 requests/day."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

from .base import (CompanyProfile, DataProvider, FinancialDataset, FiscalPeriod, MarketSnapshot, PriceSeries,
                   ProviderError, SearchResult, align_monthly, index_for_symbol, now_iso)

BASE = "https://www.alphavantage.co/query"

IS_MAP = {"revenue": "totalRevenue", "cogs": "costOfRevenue", "gross_profit": "grossProfit",
          "sga": "sellingGeneralAndAdministrative", "rnd": "researchAndDevelopment",
          "opex_total": "operatingExpenses", "operating_income": "operatingIncome",
          "da": "depreciationAndAmortization", "interest_expense": "interestExpense",
          "interest_income": "interestIncome", "pretax_income": "incomeBeforeTax", "tax": "incomeTaxExpense",
          "net_income": "netIncome", "ebitda": "ebitda"}
BS_MAP = {"cash": "cashAndCashEquivalentsAtCarryingValue", "cash_and_sti": "cashAndShortTermInvestments",
          "receivables": "currentNetReceivables", "inventory": "inventory", "current_assets": "totalCurrentAssets",
          "ppe": "propertyPlantEquipment", "goodwill_intangibles": "intangibleAssets", "total_assets": "totalAssets",
          "payables": "currentAccountsPayable", "short_term_debt": "shortTermDebt",
          "current_liabilities": "totalCurrentLiabilities", "long_term_debt": "longTermDebt",
          "total_liabilities": "totalLiabilities", "total_equity": "totalShareholderEquity",
          "stockholders_equity": "totalShareholderEquity", "retained_earnings": "retainedEarnings",
          "shares_outstanding": "commonStockSharesOutstanding"}
CF_MAP = {"cfo": "operatingCashflow", "da_cf": "depreciationDepletionAndAmortization",
          "change_wc": "changeInOperatingAssets", "capex": "capitalExpenditures",
          "cfi": "cashflowFromInvestment", "cff": "cashflowFromFinancing", "dividends": "dividendPayout",
          "buybacks": "paymentsForRepurchaseOfCommonStock", "stock_issued": "proceedsFromIssuanceOfCommonStock",
          "debt_repaid": "paymentsForRepurchaseOfEquity", "net_change_cash": "changeInCashAndCashEquivalents"}
NEGATE = {"capex", "dividends", "buybacks", "debt_repaid"}  # AV reports outflows as positives


def _f(v) -> Optional[float]:
    try:
        return None if v in (None, "None", "") else float(v)
    except (TypeError, ValueError):
        return None


class AlphaVantageProvider(DataProvider):
    id = "alphavantage"
    name = "Alpha Vantage"
    description = "Fundamentals and prices via Alpha Vantage (free tier is limited to 25 calls/day)."
    requires = "Environment variable ALPHAVANTAGE_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY", "")
        self.session = requests.Session()

    def available(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        return "" if self.available() else "ALPHAVANTAGE_API_KEY is not set"

    def _get(self, **params):
        params["apikey"] = self.api_key
        r = self.session.get(BASE, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        if "Error Message" in js or "Information" in js or "Note" in js:
            raise ProviderError(js.get("Error Message") or js.get("Information") or js.get("Note"))
        return js

    def search(self, query: str, limit: int = 8) -> List[SearchResult]:
        js = self._get(function="SYMBOL_SEARCH", keywords=query)
        return [SearchResult(x["1. symbol"], x["2. name"], x.get("4. region", "")) for x in js.get("bestMatches", [])
                if x.get("3. type") == "Equity"][:limit]

    def _monthly(self, symbol: str, name: str) -> PriceSeries:
        js = self._get(function="TIME_SERIES_MONTHLY_ADJUSTED", symbol=symbol)
        ts = js.get("Monthly Adjusted Time Series", {})
        today = datetime.utcnow().strftime("%Y-%m")
        dates = sorted(d for d in ts if d[:7] != today)[-61:]
        return PriceSeries(symbol, name, dates, [float(ts[d]["5. adjusted close"]) for d in dates])

    def fetch(self, symbol: str) -> FinancialDataset:
        ov = self._get(function="OVERVIEW", symbol=symbol)
        if not ov.get("Symbol"):
            raise ProviderError(f"Alpha Vantage has no overview for {symbol}")
        inc = self._get(function="INCOME_STATEMENT", symbol=symbol).get("annualReports", [])
        bal = self._get(function="BALANCE_SHEET", symbol=symbol).get("annualReports", [])
        cfs = self._get(function="CASH_FLOW", symbol=symbol).get("annualReports", [])
        by_date: Dict[str, FiscalPeriod] = {}

        def merge(rows, mp, tag):
            for r in rows:
                d = r["fiscalDateEnding"]
                p = by_date.setdefault(d, FiscalPeriod(period_end=d))
                for k, src in mp.items():
                    v = _f(r.get(src))
                    if v is not None and p.fields.get(k) is None:
                        p.fields[k] = -abs(v) if k in NEGATE else v
                        p.source_fields[k] = f"{tag}.{src}"
        merge(inc, IS_MAP, "INCOME_STATEMENT"); merge(bal, BS_MAP, "BALANCE_SHEET"); merge(cfs, CF_MAP, "CASH_FLOW")
        periods = [by_date[d] for d in sorted(by_date) if by_date[d].fields.get("revenue") is not None][-6:]
        for p in periods:
            p.fields.setdefault("diluted_shares", p.fields.get("shares_outstanding"))
        idx_sym, idx_name = index_for_symbol(symbol)
        stock = self._monthly(symbol, ov.get("Name", symbol))
        index = self._monthly("SPY" if idx_sym == "^GSPC" else idx_sym, idx_name)
        stock, index = align_monthly(stock, index)
        price = stock.closes[-1]
        try:
            q = self._get(function="GLOBAL_QUOTE", symbol=symbol)["Global Quote"]
            price = float(q["05. price"])
        except Exception:
            pass
        profile = CompanyProfile(symbol=symbol, name=ov.get("Name", symbol), exchange=ov.get("Exchange", ""),
                                 currency=ov.get("Currency", "USD"), sector=ov.get("Sector", ""),
                                 industry=ov.get("Industry", ""), country=ov.get("Country", ""),
                                 description=(ov.get("Description") or "")[:600])
        market = MarketSnapshot(price=price, price_date=now_iso()[:10],
                                shares_outstanding=float(ov.get("SharesOutstanding") or periods[-1].fields["diluted_shares"]),
                                currency=ov.get("Currency", "USD"), index_symbol=idx_sym, index_name=idx_name)
        return FinancialDataset(profile, market, periods, stock, index, "Alpha Vantage", now_iso(),
                                notes=["Alpha Vantage does not publish treasury yields in this integration; the default risk-free rate is used."])
