"""Yahoo Finance provider (free, no API key).

Uses the public JSON endpoints directly with ``requests`` so that it works
behind corporate proxies (the ``yfinance`` package uses curl_cffi which
ignores proxy CA bundles). Endpoints used:

* ``/v1/finance/search``                 symbol lookup by name/ticker
* ``/ws/fundamentals-timeseries/...``    annual financial statements
* ``/v8/finance/chart/{symbol}``         price, name, currency, monthly history
* ``/v8/finance/chart/%5ETNX``           10-year US Treasury yield (risk-free proxy)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from collections import Counter

from .base import (FLOW_FIELDS, MINOR_UNITS, STOCK_FIELDS, CompanyProfile, DataProvider, FinancialDataset, FiscalPeriod,
                   MarketSnapshot, PriceSeries, ProviderError, SearchResult, align_monthly, index_for_symbol, now_iso)

BASE = "https://query2.finance.yahoo.com"
# Yahoo rate-limits (HTTP 429) the long desktop-browser user agents; the short one is accepted.
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# our key -> list of Yahoo timeseries types to try in order (first non-null wins)
FIELD_MAP: Dict[str, List[str]] = {
    "revenue": ["TotalRevenue", "OperatingRevenue"],
    "cogs": ["CostOfRevenue", "ReconciledCostOfRevenue"],
    "gross_profit": ["GrossProfit"],
    "sga": ["SellingGeneralAndAdministration"],
    "rnd": ["ResearchAndDevelopment"],
    "opex_total": ["OperatingExpense"],
    "operating_income": ["OperatingIncome", "TotalOperatingIncomeAsReported"],
    "da": ["DepreciationAndAmortization", "ReconciledDepreciation", "DepreciationAmortizationDepletion"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonOperating"],
    "interest_income": ["InterestIncome", "InterestIncomeNonOperating"],
    "pretax_income": ["PretaxIncome"],
    "tax": ["TaxProvision"],
    "net_income": ["NetIncome", "NetIncomeCommonStockholders"],
    "diluted_shares": ["DilutedAverageShares"],
    "basic_shares": ["BasicAverageShares"],
    "diluted_eps": ["DilutedEPS"],
    "ebitda": ["EBITDA", "NormalizedEBITDA"],
    "cash": ["CashAndCashEquivalents"],
    "cash_and_sti": ["CashCashEquivalentsAndShortTermInvestments"],
    "receivables": ["AccountsReceivable", "Receivables"],
    "inventory": ["Inventory"],
    "current_assets": ["CurrentAssets"],
    "ppe": ["NetPPE"],
    "goodwill_intangibles": ["GoodwillAndOtherIntangibleAssets", "Goodwill"],
    "total_assets": ["TotalAssets"],
    "payables": ["AccountsPayable", "Payables"],
    "short_term_debt": ["CurrentDebtAndCapitalLeaseObligation", "CurrentDebt"],
    "current_liabilities": ["CurrentLiabilities"],
    "long_term_debt": ["LongTermDebtAndCapitalLeaseObligation", "LongTermDebt"],
    "total_liabilities": ["TotalLiabilitiesNetMinorityInterest"],
    "total_equity": ["TotalEquityGrossMinorityInterest", "StockholdersEquity"],
    "stockholders_equity": ["StockholdersEquity"],
    "retained_earnings": ["RetainedEarnings"],
    "total_debt": ["TotalDebt"],
    "shares_outstanding": ["OrdinarySharesNumber", "ShareIssued"],
    "cfo": ["OperatingCashFlow", "CashFlowFromContinuingOperatingActivities"],
    "da_cf": ["DepreciationAndAmortization", "DepreciationAmortizationDepletion"],
    "sbc": ["StockBasedCompensation"],
    "change_wc": ["ChangeInWorkingCapital"],
    "capex": ["CapitalExpenditure", "PurchaseOfPPE"],
    "cfi": ["InvestingCashFlow", "CashFlowFromContinuingInvestingActivities"],
    "cff": ["FinancingCashFlow", "CashFlowFromContinuingFinancingActivities"],
    "dividends": ["CashDividendsPaid", "CommonStockDividendPaid"],
    "buybacks": ["RepurchaseOfCapitalStock"],
    "stock_issued": ["CommonStockIssuance", "IssuanceOfCapitalStock"],
    "debt_issued": ["IssuanceOfDebt", "LongTermDebtIssuance"],
    "debt_repaid": ["RepaymentOfDebt", "LongTermDebtPayments"],
    "begin_cash": ["BeginningCashPosition"],
    "end_cash": ["EndCashPosition"],
    "net_change_cash": ["ChangesInCash"],
    "free_cash_flow": ["FreeCashFlow"],
}


def _days(a: str, b: str) -> int:
    return (datetime.strptime(b[:10], "%Y-%m-%d") - datetime.strptime(a[:10], "%Y-%m-%d")).days


class YahooProvider(DataProvider):
    id = "yahoo"
    name = "Yahoo Finance"
    description = "Free public market and fundamentals data (no key needed). Annual statements, prices, index and treasury yields."
    requires = "Internet access to query2.finance.yahoo.com"

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 25.0):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout
        # benchmark index series, FX rates and the treasury yield are shared across companies:
        # cache them for an hour so bulk builds make ~3 requests per company instead of 5-6
        self._cache: Dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, fn, ttl: float = 3600.0):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fn()
        self._cache[key] = (time.time(), val)
        return val

    # -- http ----------------------------------------------------------------
    def _get(self, path: str, params: Optional[dict] = None, retries: int = 3) -> dict:
        url = BASE + path
        last: Exception | None = None
        for i in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(1.5 * (i + 1))
                    continue
                if r.status_code == 404:
                    raise ProviderError(f"Yahoo Finance: not found ({path})")
                r.raise_for_status()
                return r.json()
            except ProviderError:
                raise
            except Exception as e:  # network / decode
                last = e
                time.sleep(0.8 * (i + 1))
        raise ProviderError(f"Yahoo Finance request failed: {last}")

    # -- api -----------------------------------------------------------------
    def search(self, query: str, limit: int = 8) -> List[SearchResult]:
        js = self._get("/v1/finance/search", {"q": query, "quotesCount": limit * 2, "newsCount": 0,
                                                 "listsCount": 0, "enableFuzzyQuery": "false"})
        out: List[SearchResult] = []
        for q in js.get("quotes", []):
            if q.get("quoteType") not in ("EQUITY",):
                continue
            out.append(SearchResult(symbol=q.get("symbol", ""), name=q.get("longname") or q.get("shortname") or "",
                                    exchange=q.get("exchDisp") or q.get("exchange") or "", type=q.get("quoteType", "EQUITY"),
                                    sector=q.get("sectorDisp") or q.get("sector") or "",
                                    industry=q.get("industryDisp") or q.get("industry") or ""))
            if len(out) >= limit:
                break
        return out

    def resolve(self, query: str) -> SearchResult:
        results = self.search(query, limit=8)
        if not results:
            raise ProviderError(f"No listed equity found for '{query}'")
        q = query.strip().upper()
        for r in results:
            if r.symbol.upper() == q:
                return r
        return results[0]

    def _chart(self, symbol: str, rng: str = "5y", interval: str = "1mo") -> dict:
        js = self._get(f"/v8/finance/chart/{requests.utils.quote(symbol)}",
                       {"range": rng, "interval": interval, "events": "div,splits", "includeAdjustedClose": "true"})
        res = js.get("chart", {}).get("result")
        if not res:
            err = js.get("chart", {}).get("error") or {}
            raise ProviderError(f"Yahoo Finance chart error for {symbol}: {err.get('description', 'no data')}")
        return res[0]

    def _lookup(self, symbol: str) -> Optional[SearchResult]:
        """Sector / industry / long name for an exact symbol (Yahoo search carries them; the chart meta does not)."""
        def fn():
            try:
                for r in self.search(symbol, limit=10):
                    if r.symbol.upper() == symbol.upper():
                        return r
            except ProviderError:
                pass
            return None
        return self._cached(f"lookup:{symbol.upper()}", fn)

    def _daily_series(self, symbol: str, name: str) -> Optional[PriceSeries]:
        """About one year of daily adjusted closes (used for equity volatility); None if unavailable."""
        try:
            res = self._chart(symbol, "1y", "1d")
        except ProviderError:
            return None
        ts = res.get("timestamp", [])
        ind = res.get("indicators", {})
        adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
        close = (ind.get("quote") or [{}])[0].get("close")
        series = adj if adj and any(v is not None for v in adj) else close
        dates, closes = [], []
        for t, c in zip(ts, series or []):
            if c is None or c <= 0:
                continue
            dates.append(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"))
            closes.append(float(c))
        if len(dates) < 30:
            return None
        return PriceSeries(symbol, name, dates, closes, interval="1d")

    def _monthly_series(self, symbol: str, name: str, min_months: int = 13) -> PriceSeries:
        res = self._chart(symbol, "6y", "1mo")
        ts = res.get("timestamp", [])
        ind = res.get("indicators", {})
        adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
        close = (ind.get("quote") or [{}])[0].get("close")
        series = adj if adj and any(v is not None for v in adj) else close
        dates, closes = [], []
        seen = set()
        for t, c in zip(ts, series or []):
            if c is None:
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            if d[:7] in seen:
                continue
            seen.add(d[:7])
            dates.append(d)
            closes.append(float(c))
        # drop the partial current month so returns are true month-over-month observations
        today = datetime.now(timezone.utc).strftime("%Y-%m")
        if dates and dates[-1][:7] == today:
            dates, closes = dates[:-1], closes[:-1]
        if len(dates) < min_months:
            raise ProviderError(f"Insufficient price history for {symbol} ({len(dates)} months)")
        return PriceSeries(symbol, name, dates[-61:], closes[-61:])

    def _fundamentals(self, symbol: str) -> tuple[List[FiscalPeriod], str]:
        """Annual statements plus the currency the statements are reported in."""
        types = sorted({t for lst in FIELD_MAP.values() for t in lst})
        now = int(time.time())
        js = self._get(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{requests.utils.quote(symbol)}",
                       {"type": ",".join("annual" + t for t in types), "period1": now - 12 * 366 * 86400,
                        "period2": now + 86400, "merge": "false"})
        result = js.get("timeseries", {}).get("result") or []
        by_type: Dict[str, Dict[str, float]] = {}
        currencies: Counter = Counter()
        for res in result:
            t = res["meta"]["type"][0]
            vals = {}
            for v in res.get(t) or []:
                if v and v.get("reportedValue") and v["reportedValue"].get("raw") is not None:
                    vals[v["asOfDate"]] = float(v["reportedValue"]["raw"])
                    if v.get("currencyCode") and t.endswith(("TotalRevenue", "TotalAssets", "NetIncome")):
                        currencies[v["currencyCode"]] += 1
            by_type[t.replace("annual", "", 1)] = vals
        dates = sorted({d for t in FIELD_MAP["revenue"] for d in by_type.get(t, {})})
        periods: List[FiscalPeriod] = []
        for d in dates:
            fields: Dict[str, Optional[float]] = {}
            src: Dict[str, str] = {}
            for key, cands in FIELD_MAP.items():
                fields[key] = None
                for c in cands:
                    if d in by_type.get(c, {}):
                        fields[key] = by_type[c][d]
                        src[key] = "annual" + c
                        break
            if fields.get("revenue") is None or fields.get("total_assets") is None:
                continue
            periods.append(FiscalPeriod(period_end=d, fields=fields, source_fields=src))
        if not periods:
            raise ProviderError(f"Yahoo Finance has no annual financial statements for {symbol}")
        stmt_ccy = currencies.most_common(1)[0][0] if currencies else ""
        return periods[-6:], stmt_ccy

    def _ltm(self, symbol: str) -> tuple[Optional[FiscalPeriod], Dict[str, object]]:
        """Latest twelve months from the quarterly statements: flows summed over the four most recent consecutive
        quarters, balance sheet at the latest quarter end within one quarter of the LTM end. Returns (None, meta)
        with the reason when the quarterly data cannot support it (semi-annual reporters, gaps, no balance sheet)."""
        types = sorted({t for lst in FIELD_MAP.values() for t in lst})
        now = int(time.time())
        try:
            js = self._get(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{requests.utils.quote(symbol)}",
                           {"type": ",".join("quarterly" + t for t in types), "period1": now - int(2.3 * 366 * 86400),
                            "period2": now + 86400, "merge": "false"})
        except ProviderError as e:
            return None, {"available": False, "reason": f"quarterly statements not retrievable ({str(e)[:80]})"}
        by_type: Dict[str, Dict[str, float]] = {}
        for res in js.get("timeseries", {}).get("result") or []:
            t = res["meta"]["type"][0]
            vals = {}
            for v in res.get(t) or []:
                if v and v.get("reportedValue") and v["reportedValue"].get("raw") is not None:
                    vals[v["asOfDate"]] = float(v["reportedValue"]["raw"])
            by_type[t.replace("quarterly", "", 1)] = vals

        def series(key: str) -> tuple[Dict[str, float], str]:
            for c in FIELD_MAP[key]:
                if by_type.get(c):
                    return by_type[c], "quarterly" + c
            return {}, ""

        rev, _ = series("revenue")
        dates = sorted(rev)
        if len(dates) < 4:
            return None, {"available": False, "reason": f"only {len(dates)} quarterly income statements available"}
        # the four most recent quarter ends must be consecutive quarters (about 13 weeks apart)
        q = dates[-4:]
        gaps = [_days(q[i], q[i + 1]) for i in range(3)]
        if not all(75 <= g <= 105 for g in gaps):
            return None, {"available": False, "reason": f"the latest quarterly income statements are not four consecutive quarters ({', '.join(q)})"}
        ta, _ = series("total_assets")
        bs_dates = [d for d in sorted(ta) if d <= q[-1] and _days(d, q[-1]) <= 100]
        if not bs_dates:
            return None, {"available": False, "reason": "no quarterly balance sheet within a quarter of the latest income statement"}
        bs_date = bs_dates[-1]
        fields: Dict[str, Optional[float]] = {}
        src: Dict[str, str] = {}
        missing_flows: List[str] = []
        for key in FLOW_FIELDS:
            ser, name = series(key)
            if ser and all(d in ser for d in q):
                fields[key] = sum(ser[d] for d in q)
                src[key] = f"LTM: sum of 4 quarters of {name}"
            else:
                fields[key] = None
                if ser:
                    missing_flows.append(key)
        for key in STOCK_FIELDS:
            ser, name = series(key)
            if ser and bs_date in ser:
                fields[key] = ser[bs_date]
                src[key] = f"quarter end {bs_date}: {name}"
            elif ser and q[-1] in ser:
                fields[key] = ser[q[-1]]
                src[key] = f"quarter end {q[-1]}: {name}"
            else:
                fields[key] = None
        eps, name = series("diluted_eps")
        fields["diluted_eps"] = sum(eps[d] for d in q) if eps and all(d in eps for d in q) else None
        if fields["diluted_eps"] is not None:
            src["diluted_eps"] = f"LTM: sum of 4 quarters of {name}"
        end_cash, name = series("end_cash")
        fields["end_cash"] = end_cash.get(q[-1]) if end_cash else None
        if fields["end_cash"] is not None:
            src["end_cash"] = f"quarter end {q[-1]}: {name}"
        begin_cash: Optional[float] = None
        if end_cash:
            earlier = [d for d in sorted(end_cash) if d < q[0]]
            if earlier and 75 <= _days(earlier[-1], q[0]) <= 105:
                begin_cash = end_cash[earlier[-1]]
                src["begin_cash"] = f"quarter end {earlier[-1]}: {name}"
        fields["begin_cash"] = begin_cash
        if fields.get("revenue") is None or fields.get("total_assets") is None:
            return None, {"available": False, "reason": "quarterly revenue or total assets missing"}
        meta = {"available": True, "quarters": q, "balance_date": bs_date, "missing_flows": missing_flows,
                "label": f"LTM {q[-1][:7]}"}
        return FiscalPeriod(period_end=q[-1], fields=fields, source_fields=src), meta

    def _market_cap(self, symbol: str) -> Optional[float]:
        """Yahoo's own market capitalisation (listing currency, major units): the trailing figure, else the latest quarterly one."""
        now = int(time.time())
        try:
            js = self._get(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{requests.utils.quote(symbol)}",
                           {"type": "trailingMarketCap,quarterlyMarketCap", "period1": now - 400 * 86400, "period2": now + 86400, "merge": "false"})
        except ProviderError:
            return None
        found: Dict[str, float] = {}
        for res in js.get("timeseries", {}).get("result") or []:
            t = res["meta"]["type"][0]
            vals = [v["reportedValue"]["raw"] for v in (res.get(t) or []) if v and v.get("reportedValue") and v["reportedValue"].get("raw")]
            if vals:
                found[t] = float(vals[-1])
        return found.get("trailingMarketCap") or found.get("quarterlyMarketCap")

    def _fx_rate(self, from_ccy: str, to_ccy: str) -> Optional[float]:
        """Spot rate: 1 unit of from_ccy in to_ccy, via Yahoo FX quotes (tries both pair orders)."""
        if from_ccy == to_ccy:
            return 1.0
        for sym, invert in ((f"{from_ccy}{to_ccy}=X", False), (f"{to_ccy}{from_ccy}=X", True)):
            try:
                px = self._chart(sym, "5d", "1d")["meta"].get("regularMarketPrice")
                if px:
                    return (1.0 / float(px)) if invert else float(px)
            except Exception:
                continue
        return None

    def _risk_free(self) -> tuple[Optional[float], str]:
        try:
            res = self._chart("^TNX", "5d", "1d")
            y = res["meta"].get("regularMarketPrice")
            if y is not None:
                return float(y) / 100.0, "US 10-year Treasury yield (^TNX, Yahoo Finance)"
        except Exception:
            pass
        return None, ""

    def fetch(self, symbol: str, **options) -> FinancialDataset:
        require_history = bool(options.get("require_history", True))
        chart = self._chart(symbol, "1y", "1d")
        meta = chart["meta"]
        idx_sym, idx_name = index_for_symbol(symbol)
        periods, stmt_ccy = self._fundamentals(symbol)
        name = meta.get("longName") or meta.get("shortName") or symbol
        stock = self._monthly_series(symbol, name, min_months=13 if require_history else 2)
        index = self._cached(f"index:{idx_sym}", lambda: self._monthly_series(idx_sym, idx_name))
        stock, index = align_monthly(stock, index)
        daily = self._daily_series(symbol, name)
        ltm, ltm_meta = self._ltm(symbol)
        rf, rf_src = self._cached("rf", self._risk_free)
        info = self._lookup(symbol)
        notes: List[str] = []
        if ltm is not None and ltm.period_end <= periods[-1].period_end:
            ltm_meta = {"available": False, "reason": f"the latest fiscal year ({periods[-1].period_end}) is already the most recent period"}
            ltm = None
        if ltm is None:
            notes.append(f"Latest-twelve-months basis not available from quarterly data ({ltm_meta.get('reason', 'unknown')}); "
                         "the default-risk analysis uses the latest fiscal year.")
        elif ltm_meta.get("missing_flows"):
            notes.append("LTM period: no quarterly data for " + ", ".join(ltm_meta["missing_flows"]) + " (treated as not reported).")
        if len(stock.closes) < 13:
            notes.append(f"Only {len(stock.closes)} months of price history are available (recent listing or re-listing): "
                         "beta and volatility estimates are unreliable.")
        if daily is None:
            notes.append("Daily price history unavailable; equity volatility falls back to monthly returns.")
        last = periods[-1]
        stmt_ccy = stmt_ccy or ""
        # market capitalisation uses the most recent share count: the latest quarter end when an LTM period exists
        share_src = ltm if (ltm is not None and (ltm.get("shares_outstanding") or ltm.get("diluted_shares"))) else last
        shares = share_src.get("shares_outstanding") or share_src.get("diluted_shares")
        if shares is None:
            raise ProviderError(f"Share count unavailable for {symbol}")
        if share_src.get("shares_outstanding") is None:
            notes.append("Shares outstanding proxied by diluted weighted-average shares of the latest "
                         + ("quarter." if share_src is ltm else "fiscal year."))
        price_ts = meta.get("regularMarketTime")
        price_date = datetime.fromtimestamp(price_ts, tz=timezone.utc).strftime("%Y-%m-%d") if price_ts else now_iso()[:10]
        # --- currency alignment: the model runs in the reporting currency of the statements ---
        listing_ccy = meta.get("currency") or "USD"
        listing_price = float(meta["regularMarketPrice"])
        price = listing_price
        hi, lo = meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow")
        if listing_ccy in MINOR_UNITS:
            major, div = MINOR_UNITS[listing_ccy]
            notes.append(f"Share price quoted in {listing_ccy} (minor units): {listing_price:,.2f} {listing_ccy} = {listing_price / div:,.2f} {major}.")
            price, listing_ccy = price / div, major
            hi, lo = (hi / div if hi else hi), (lo / div if lo else lo)
        source_mcap = self._market_cap(symbol)                    # independent check on the share count (splits, share classes, units)
        implied_shares = (source_mcap / price) if (source_mcap and price > 0) else None
        currency = stmt_ccy or listing_ccy
        fx = None
        if currency != listing_ccy:
            fx = self._cached(f"fx:{listing_ccy}{currency}", lambda: self._fx_rate(listing_ccy, currency))
            if fx is None:
                notes.append(f"WARNING: the share price is quoted in {listing_ccy} but the statements are in {currency} and no FX rate could be retrieved; "
                             f"the price was left unconverted - override 'Current share price' in Assumptions.")
            else:
                notes.append(f"Statements are reported in {currency} while the share is quoted in {listing_ccy}: price {price:,.2f} {listing_ccy} "
                             f"converted at {fx:,.4f} = {price * fx:,.2f} {currency}. If this listing is a depositary receipt (ADR/GDR), "
                             f"adjust the implied value for the depositary share ratio.")
                price, hi, lo = price * fx, (hi * fx if hi else hi), (lo * fx if lo else lo)
        fx_usd = 1.0 if currency == "USD" else self._cached(f"fx:{currency}USD", lambda: self._fx_rate(currency, "USD"))
        if fx_usd is None:
            notes.append(f"No {currency}/USD rate could be retrieved; USD-based size measures use the reporting currency unconverted.")
        profile = CompanyProfile(symbol=symbol, name=name,
                                 exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "",
                                 currency=currency, fiscal_year_end_month=int(last.period_end[5:7]),
                                 sector=(info.sector if info else ""), industry=(info.industry if info else ""))
        market = MarketSnapshot(price=price, price_date=price_date,
                                shares_outstanding=float(shares), currency=currency,
                                fifty_two_week_high=hi, fifty_two_week_low=lo,
                                risk_free_rate=rf, risk_free_source=rf_src, index_symbol=idx_sym, index_name=idx_name,
                                listing_currency=listing_ccy, listing_price=listing_price, fx_rate=fx, fx_to_usd=fx_usd,
                                source_market_cap=source_mcap, source_implied_shares=implied_shares)
        if rf is None:
            notes.append("Risk-free rate could not be retrieved; a default of 4.0% is used - override in Assumptions.")
        if idx_sym != "^GSPC":
            notes.append(f"Beta regressed against {idx_name}; risk-free rate is the US 10-year yield and may need a local-currency adjustment.")
        missing = [k for k, v in last.fields.items() if v is None]
        if missing:
            notes.append("Fields not reported by the source for the latest fiscal year (treated as zero): " + ", ".join(missing) + ".")
        return FinancialDataset(profile=profile, market=market, periods=periods, stock_prices=stock,
                                index_prices=index, source="Yahoo Finance", retrieved_at=now_iso(), notes=notes,
                                daily_prices=daily, ltm=ltm, ltm_meta=ltm_meta)
