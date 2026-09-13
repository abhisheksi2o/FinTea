"""Normalised data schema shared by every data source.

All monetary values are stored in the *reporting currency, raw units* (not
millions). The model builder converts to millions. Missing values are ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# Field keys of a fiscal period. Sign convention follows the cash-flow statement
# (outflows negative: capex, dividends, buybacks, debt repayment).
INCOME_FIELDS = [
    "revenue", "cogs", "gross_profit", "sga", "rnd", "opex_total", "operating_income",
    "da", "interest_expense", "interest_income", "pretax_income", "tax", "net_income",
    "diluted_shares", "basic_shares", "diluted_eps", "ebitda",
]
BALANCE_FIELDS = [
    "cash", "cash_and_sti", "receivables", "inventory", "current_assets", "ppe",
    "goodwill_intangibles", "total_assets", "payables", "short_term_debt",
    "current_liabilities", "long_term_debt", "total_liabilities", "total_equity",
    "stockholders_equity", "retained_earnings", "total_debt", "shares_outstanding",
]
CASHFLOW_FIELDS = [
    "cfo", "da_cf", "sbc", "change_wc", "capex", "cfi", "cff", "dividends", "buybacks",
    "stock_issued", "debt_issued", "debt_repaid", "begin_cash", "end_cash",
    "net_change_cash", "free_cash_flow",
]
ALL_FIELDS = INCOME_FIELDS + BALANCE_FIELDS + CASHFLOW_FIELDS

FIELD_LABELS = {
    "revenue": "Total revenue", "cogs": "Cost of revenue", "gross_profit": "Gross profit (reported)",
    "sga": "Selling, general & administrative", "rnd": "Research & development",
    "opex_total": "Total operating expenses (reported)", "operating_income": "Operating income (EBIT)",
    "da": "Depreciation & amortisation", "interest_expense": "Interest expense",
    "interest_income": "Interest income", "pretax_income": "Pre-tax income", "tax": "Income tax provision",
    "net_income": "Net income", "diluted_shares": "Diluted weighted avg. shares",
    "basic_shares": "Basic weighted avg. shares", "diluted_eps": "Diluted EPS (reported)",
    "ebitda": "EBITDA (reported)",
    "cash": "Cash & cash equivalents", "cash_and_sti": "Cash, equivalents & short-term investments",
    "receivables": "Accounts receivable", "inventory": "Inventory", "current_assets": "Total current assets",
    "ppe": "Net PP&E", "goodwill_intangibles": "Goodwill & intangibles", "total_assets": "Total assets",
    "payables": "Accounts payable", "short_term_debt": "Short-term debt & current leases",
    "current_liabilities": "Total current liabilities", "long_term_debt": "Long-term debt & leases",
    "total_liabilities": "Total liabilities", "total_equity": "Total equity (incl. minority)",
    "stockholders_equity": "Stockholders' equity", "retained_earnings": "Retained earnings",
    "total_debt": "Total debt (reported)", "shares_outstanding": "Shares outstanding (period end)",
    "cfo": "Cash from operations", "da_cf": "D&A (cash flow statement)", "sbc": "Stock-based compensation",
    "change_wc": "Change in working capital", "capex": "Capital expenditure", "cfi": "Cash from investing",
    "cff": "Cash from financing", "dividends": "Dividends paid", "buybacks": "Share repurchases",
    "stock_issued": "Share issuance", "debt_issued": "Debt issued", "debt_repaid": "Debt repaid",
    "begin_cash": "Beginning cash position", "end_cash": "Ending cash position",
    "net_change_cash": "Net change in cash", "free_cash_flow": "Free cash flow (reported)",
}


@dataclass
class CompanyProfile:
    symbol: str
    name: str
    exchange: str = ""
    currency: str = "USD"
    sector: str = ""
    industry: str = ""
    country: str = ""
    description: str = ""
    fiscal_year_end_month: Optional[int] = None


@dataclass
class MarketSnapshot:
    price: float
    price_date: str
    shares_outstanding: float
    currency: str = "USD"
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    risk_free_rate: Optional[float] = None       # decimal, e.g. 0.042
    risk_free_source: str = ""
    index_symbol: str = "^GSPC"
    index_name: str = "S&P 500"

    @property
    def market_cap(self) -> float:
        return self.price * self.shares_outstanding


@dataclass
class FiscalPeriod:
    period_end: str                      # ISO date
    fields: Dict[str, Optional[float]] = field(default_factory=dict)
    source_fields: Dict[str, str] = field(default_factory=dict)  # our key -> provider field name

    def get(self, key: str) -> Optional[float]:
        return self.fields.get(key)

    @property
    def fiscal_year(self) -> int:
        return int(self.period_end[:4])


@dataclass
class PriceSeries:
    symbol: str
    name: str
    dates: List[str]
    closes: List[float]
    interval: str = "1mo"


@dataclass
class FinancialDataset:
    profile: CompanyProfile
    market: MarketSnapshot
    periods: List[FiscalPeriod]          # ascending by period_end
    stock_prices: PriceSeries
    index_prices: PriceSeries
    source: str
    retrieved_at: str
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FinancialDataset":
        return cls(
            profile=CompanyProfile(**d["profile"]),
            market=MarketSnapshot(**d["market"]),
            periods=[FiscalPeriod(**p) for p in d["periods"]],
            stock_prices=PriceSeries(**d["stock_prices"]),
            index_prices=PriceSeries(**d["index_prices"]),
            source=d["source"], retrieved_at=d["retrieved_at"], notes=list(d.get("notes", [])),
        )


@dataclass
class SearchResult:
    symbol: str
    name: str
    exchange: str = ""
    type: str = "EQUITY"


class ProviderError(Exception):
    """Raised when a provider cannot serve a request (network, auth, missing data)."""


class DataProvider:
    """Interface every data source implements."""

    id: str = "base"
    name: str = "Base"
    description: str = ""
    requires: str = ""  # human description of configuration needed

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def search(self, query: str, limit: int = 8) -> List[SearchResult]:  # pragma: no cover - interface
        raise NotImplementedError

    def fetch(self, symbol: str) -> FinancialDataset:  # pragma: no cover - interface
        raise NotImplementedError

    def info(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "available": self.available(), "requires": self.requires,
                "reason": self.unavailable_reason()}


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def align_monthly(stock: PriceSeries, index: PriceSeries) -> tuple[PriceSeries, PriceSeries]:
    """Keep only month-ends present in both series (by YYYY-MM)."""
    def by_month(s: PriceSeries):
        out = {}
        for d, c in zip(s.dates, s.closes):
            if c is not None:
                out[d[:7]] = (d, float(c))
        return out
    a, b = by_month(stock), by_month(index)
    months = sorted(set(a) & set(b))
    return (PriceSeries(stock.symbol, stock.name, [a[m][0] for m in months], [a[m][1] for m in months]),
            PriceSeries(index.symbol, index.name, [b[m][0] for m in months], [b[m][1] for m in months]))


# Exchange suffix -> benchmark index used for the beta regression
INDEX_BY_SUFFIX = {
    "": ("^GSPC", "S&P 500"), "NS": ("^NSEI", "NIFTY 50"), "BO": ("^BSESN", "BSE SENSEX"),
    "L": ("^FTSE", "FTSE 100"), "DE": ("^GDAXI", "DAX"), "PA": ("^FCHI", "CAC 40"),
    "T": ("^N225", "Nikkei 225"), "HK": ("^HSI", "Hang Seng"), "TO": ("^GSPTSE", "S&P/TSX"),
    "AX": ("^AXJO", "S&P/ASX 200"), "SS": ("000001.SS", "SSE Composite"), "SZ": ("399001.SZ", "SZSE Component"),
    "KS": ("^KS11", "KOSPI"), "SW": ("^SSMI", "SMI"), "AS": ("^AEX", "AEX"), "MI": ("FTSEMIB.MI", "FTSE MIB"),
    "MC": ("^IBEX", "IBEX 35"), "SA": ("^BVSP", "Bovespa"), "MX": ("^MXX", "IPC Mexico"),
    "TW": ("^TWII", "TAIEX"), "SI": ("^STI", "Straits Times"), "JO": ("^J203.JO", "JSE All Share"),
    "ST": ("^OMX", "OMX Stockholm 30"), "CO": ("^OMXC25", "OMX Copenhagen 25"), "OL": ("^OSEAX", "Oslo All Share"),
    "HE": ("^OMXH25", "OMX Helsinki 25"), "BR": ("^BFX", "BEL 20"), "VI": ("^ATX", "ATX"),
}


def index_for_symbol(symbol: str) -> tuple[str, str]:
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    return INDEX_BY_SUFFIX.get(suffix, ("^GSPC", "S&P 500"))
