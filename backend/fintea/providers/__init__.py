"""Data provider registry."""
from __future__ import annotations

from typing import Dict, List

from .alpha_vantage import AlphaVantageProvider
from .base import DataProvider, FinancialDataset, ProviderError, SearchResult
from .bloomberg import BloombergProvider
from .fmp import FMPProvider
from .normalize import normalize
from .sample import SampleProvider
from .yahoo import YahooProvider

_PROVIDERS: Dict[str, DataProvider] = {}


def registry() -> Dict[str, DataProvider]:
    if not _PROVIDERS:
        for p in (YahooProvider(), BloombergProvider(), FMPProvider(), AlphaVantageProvider(), SampleProvider()):
            _PROVIDERS[p.id] = p
    return _PROVIDERS


def get_provider(provider_id: str = "yahoo") -> DataProvider:
    reg = registry()
    if provider_id not in reg:
        raise ProviderError(f"Unknown data source '{provider_id}'. Available: {', '.join(reg)}")
    p = reg[provider_id]
    if not p.available():
        raise ProviderError(f"{p.name} is not available: {p.unavailable_reason()}")
    return p


def list_providers() -> List[dict]:
    return [p.info() for p in registry().values()]


def load_dataset(query: str, provider_id: str = "yahoo") -> FinancialDataset:
    """Resolve a company name or ticker and return a normalised dataset."""
    p = get_provider(provider_id)
    symbol = query.strip()
    if hasattr(p, "resolve"):
        symbol = p.resolve(query).symbol  # type: ignore[attr-defined]
    else:
        hits = p.search(query, limit=50)
        if hits:
            exact = [h for h in hits if h.symbol.upper() == query.strip().upper()]
            symbol = (exact or hits)[0].symbol
    ds = p.fetch(symbol)
    return normalize(ds)


__all__ = ["registry", "get_provider", "list_providers", "load_dataset", "normalize", "DataProvider",
           "FinancialDataset", "ProviderError", "SearchResult"]
