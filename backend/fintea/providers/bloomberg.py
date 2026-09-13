"""Bloomberg Desktop API / B-PIPE provider.

Requires the ``blpapi`` Python package and a running Bloomberg Terminal
(Desktop API on localhost:8194) or Server API / B-PIPE credentials. Configure
with BLOOMBERG_HOST / BLOOMBERG_PORT. Without a terminal this provider reports
itself as unavailable; the rest of the application keeps working.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Dict, List, Optional

from .base import (CompanyProfile, DataProvider, FinancialDataset, FiscalPeriod, MarketSnapshot, PriceSeries,
                   ProviderError, SearchResult, align_monthly, index_for_symbol, now_iso)

try:  # pragma: no cover - only present on Bloomberg workstations
    import blpapi  # type: ignore
except Exception:  # pragma: no cover
    blpapi = None

# Bloomberg fundamental fields -> our schema (annual, FA fields)
FIELD_MAP: Dict[str, str] = {
    "revenue": "SALES_REV_TURN", "cogs": "IS_COGS_TO_FE_AND_PP_AND_G", "gross_profit": "GROSS_PROFIT",
    "sga": "IS_SG_AND_A_EXPENSE", "rnd": "IS_RD_EXPEND", "opex_total": "IS_OPERATING_EXPN",
    "operating_income": "IS_OPER_INC", "da": "CF_DEPR_AMORT", "interest_expense": "IS_INT_EXPENSE",
    "interest_income": "IS_INT_INC", "pretax_income": "PRETAX_INC", "tax": "IS_INC_TAX_EXP",
    "net_income": "NET_INCOME", "diluted_shares": "IS_AVG_NUM_SH_FOR_EPS", "basic_shares": "IS_AVG_NUM_SH_FOR_EPS",
    "diluted_eps": "IS_DILUTED_EPS", "ebitda": "EBITDA",
    "cash": "BS_CASH_NEAR_CASH_ITEM", "cash_and_sti": "CASH_AND_MARKETABLE_SECURITIES", "receivables": "BS_ACCT_NOTE_RCV",
    "inventory": "BS_INVENTORIES", "current_assets": "BS_CUR_ASSET_REPORT", "ppe": "BS_NET_FIX_ASSET",
    "goodwill_intangibles": "BS_DISCLOSED_INTANGIBLES", "total_assets": "BS_TOT_ASSET", "payables": "BS_ACCT_PAYABLE",
    "short_term_debt": "BS_ST_BORROW", "current_liabilities": "BS_CUR_LIAB", "long_term_debt": "BS_LT_BORROW",
    "total_liabilities": "BS_TOT_LIAB2", "total_equity": "TOTAL_EQUITY", "stockholders_equity": "TOT_COMMON_EQY",
    "retained_earnings": "BS_RETAIN_EARN", "total_debt": "SHORT_AND_LONG_TERM_DEBT", "shares_outstanding": "BS_SH_OUT",
    "cfo": "CF_CASH_FROM_OPER", "da_cf": "CF_DEPR_AMORT", "sbc": "CF_STOCK_BASED_COMPENSATION",
    "change_wc": "CF_CHNG_NON_CASH_WORK_CAP", "capex": "CF_CAP_EXPEND_PRPTY_ADD", "cfi": "CF_CASH_FROM_INV_ACT",
    "cff": "CF_CASH_FROM_FNC_ACT", "dividends": "CF_DVD_PAID", "buybacks": "CF_REPURCH_OF_COMMON_STOCK",
    "stock_issued": "CF_ISSUE_OF_COMMON_STOCK", "debt_issued": "CF_LT_DEBT_ISSUANCE", "debt_repaid": "CF_LT_DEBT_REPAYMENT",
    "end_cash": "CF_CASH_AT_END_OF_PERIOD", "begin_cash": "CF_CASH_AT_BEGIN_OF_PERIOD",
    "net_change_cash": "CF_NET_CHNG_CASH", "free_cash_flow": "CF_FREE_CASH_FLOW",
}


class BloombergProvider(DataProvider):
    id = "bloomberg"
    name = "Bloomberg (Desktop API / B-PIPE)"
    description = "Bloomberg fundamentals (FA fields), pricing and curves through blpapi."
    requires = "blpapi package plus a Bloomberg Terminal (localhost:8194) or B-PIPE; BLOOMBERG_HOST / BLOOMBERG_PORT"

    def __init__(self):
        self.host = os.environ.get("BLOOMBERG_HOST", "localhost")
        self.port = int(os.environ.get("BLOOMBERG_PORT", "8194"))
        self._session = None

    def available(self) -> bool:
        return blpapi is not None and os.environ.get("BLOOMBERG_ENABLED", "1") == "1"

    def unavailable_reason(self) -> str:
        if blpapi is None:
            return "blpapi is not installed (pip install blpapi with a Bloomberg Terminal or B-PIPE entitlement)"
        return ""

    # -- session -------------------------------------------------------------
    def _svc(self):  # pragma: no cover - requires terminal
        if self._session is None:
            opts = blpapi.SessionOptions()
            opts.setServerHost(self.host)
            opts.setServerPort(self.port)
            s = blpapi.Session(opts)
            if not s.start() or not s.openService("//blp/refdata"):
                raise ProviderError(f"Cannot connect to Bloomberg at {self.host}:{self.port}")
            self._session = s
        return self._session, self._session.getService("//blp/refdata")

    def _send(self, request):  # pragma: no cover - requires terminal
        session, _ = self._svc()
        session.sendRequest(request)
        msgs = []
        while True:
            ev = session.nextEvent(10000)
            for msg in ev:
                msgs.append(msg)
            if ev.eventType() == blpapi.Event.RESPONSE:
                break
        return msgs

    @staticmethod
    def _bbg_symbol(symbol: str) -> str:
        if " " in symbol:
            return symbol
        base, _, suffix = symbol.partition(".")
        mkt = {"": "US", "L": "LN", "NS": "IN", "BO": "IB", "T": "JP", "HK": "HK", "DE": "GR", "PA": "FP",
               "TO": "CN", "AX": "AU", "SW": "SW", "AS": "NA", "MI": "IM", "MC": "SM"}.get(suffix.upper(), "US")
        return f"{base} {mkt} Equity"

    # -- api -----------------------------------------------------------------
    def search(self, query: str, limit: int = 8) -> List[SearchResult]:  # pragma: no cover - requires terminal
        _, svc = self._svc()
        req = svc.createRequest("ReferenceDataRequest")
        sym = self._bbg_symbol(query)
        req.getElement("securities").appendValue(sym)
        for f in ("NAME", "EXCH_CODE"):
            req.getElement("fields").appendValue(f)
        out = []
        for msg in self._send(req):
            for sd in msg.getElement("securityData").values():
                fd = sd.getElement("fieldData")
                if fd.hasElement("NAME"):
                    out.append(SearchResult(sd.getElementAsString("security"), fd.getElementAsString("NAME"),
                                            fd.getElementAsString("EXCH_CODE") if fd.hasElement("EXCH_CODE") else ""))
        return out[:limit]

    def _history(self, sec: str, name: str) -> PriceSeries:  # pragma: no cover - requires terminal
        _, svc = self._svc()
        req = svc.createRequest("HistoricalDataRequest")
        req.getElement("securities").appendValue(sec)
        req.getElement("fields").appendValue("PX_LAST")
        req.set("periodicitySelection", "MONTHLY")
        end = date.today().replace(day=1) - timedelta(days=1)
        req.set("startDate", (end - timedelta(days=365 * 5 + 40)).strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        dates, closes = [], []
        for msg in self._send(req):
            for row in msg.getElement("securityData").getElement("fieldData").values():
                dates.append(row.getElementAsDatetime("date").strftime("%Y-%m-%d"))
                closes.append(row.getElementAsFloat("PX_LAST"))
        return PriceSeries(sec, name, dates[-61:], closes[-61:])

    def fetch(self, symbol: str) -> FinancialDataset:  # pragma: no cover - requires terminal
        _, svc = self._svc()
        sec = self._bbg_symbol(symbol)
        # reference data: profile + latest market data
        req = svc.createRequest("ReferenceDataRequest")
        req.getElement("securities").appendValue(sec)
        for f in ("NAME", "PX_LAST", "EQY_SH_OUT", "CRNCY", "GICS_SECTOR_NAME", "GICS_INDUSTRY_NAME",
                  "COUNTRY_FULL_NAME", "EXCH_CODE", "FUND_PER"):
            req.getElement("fields").appendValue(f)
        ref = {}
        for msg in self._send(req):
            for sd in msg.getElement("securityData").values():
                fd = sd.getElement("fieldData")
                for i in range(fd.numElements()):
                    el = fd.getElement(i)
                    ref[str(el.name())] = el.getValue()
        # annual fundamentals for the last 6 fiscal years
        periods: List[FiscalPeriod] = []
        for years_back in range(5, -1, -1):
            r = svc.createRequest("ReferenceDataRequest")
            r.getElement("securities").appendValue(sec)
            for f in set(FIELD_MAP.values()) | {"FUNDAMENTAL_PUBLIC_DATE", "LATEST_PERIOD_END_DT_FULL_RECORD"}:
                r.getElement("fields").appendValue(f)
            ov = r.getElement("overrides")
            for k, v in (("FUND_PER", "A"), ("EQY_FUND_RELATIVE_PERIOD", f"-{years_back}AY" if years_back else "0AY")):
                o = ov.appendElement()
                o.setElement("fieldId", k)
                o.setElement("value", v)
            fields: Dict[str, Optional[float]] = {}
            end_dt = None
            for msg in self._send(r):
                for sd in msg.getElement("securityData").values():
                    fd = sd.getElement("fieldData")
                    if fd.hasElement("LATEST_PERIOD_END_DT_FULL_RECORD"):
                        end_dt = fd.getElementAsDatetime("LATEST_PERIOD_END_DT_FULL_RECORD").strftime("%Y-%m-%d")
                    for k, bf in FIELD_MAP.items():
                        fields[k] = fd.getElementAsFloat(bf) * 1e6 if fd.hasElement(bf) else None  # Bloomberg FA fields are in millions
            if end_dt and fields.get("revenue") is not None:
                for k in ("capex", "dividends", "buybacks", "debt_repaid"):
                    if fields.get(k) is not None:
                        fields[k] = -abs(fields[k])
                periods.append(FiscalPeriod(period_end=end_dt, fields=fields,
                                            source_fields={k: v for k, v in FIELD_MAP.items()}))
        if not periods:
            raise ProviderError(f"Bloomberg returned no fundamentals for {sec}")
        idx_sym, idx_name = index_for_symbol(symbol)
        bbg_index = {"^GSPC": "SPX Index", "^NSEI": "NIFTY Index", "^FTSE": "UKX Index", "^GDAXI": "DAX Index",
                     "^N225": "NKY Index", "^HSI": "HSI Index", "^GSPTSE": "SPTSX Index"}.get(idx_sym, "SPX Index")
        stock = self._history(sec, ref.get("NAME", symbol))
        index = self._history(bbg_index, idx_name)
        stock, index = align_monthly(stock, index)
        rf = None
        try:
            r = svc.createRequest("ReferenceDataRequest")
            r.getElement("securities").appendValue("USGG10YR Index")
            r.getElement("fields").appendValue("PX_LAST")
            for msg in self._send(r):
                for sd in msg.getElement("securityData").values():
                    rf = sd.getElement("fieldData").getElementAsFloat("PX_LAST") / 100
        except Exception:
            pass
        profile = CompanyProfile(symbol=symbol, name=ref.get("NAME", symbol), exchange=ref.get("EXCH_CODE", ""),
                                 currency=ref.get("CRNCY", "USD"), sector=ref.get("GICS_SECTOR_NAME", ""),
                                 industry=ref.get("GICS_INDUSTRY_NAME", ""), country=ref.get("COUNTRY_FULL_NAME", ""))
        market = MarketSnapshot(price=float(ref["PX_LAST"]), price_date=now_iso()[:10],
                                shares_outstanding=float(ref["EQY_SH_OUT"]) * 1e6, currency=ref.get("CRNCY", "USD"),
                                risk_free_rate=rf, risk_free_source="USGG10YR Index (Bloomberg)" if rf else "",
                                index_symbol=bbg_index, index_name=idx_name)
        return FinancialDataset(profile, market, periods, stock, index, "Bloomberg", now_iso())
