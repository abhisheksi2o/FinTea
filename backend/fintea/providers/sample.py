"""Offline provider backed by JSON snapshots taken from Yahoo Finance.

Used for demos, tests and environments without internet access. Snapshots are
clearly labelled with their retrieval date inside the workbook.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .base import DataProvider, FinancialDataset, ProviderError, SearchResult

DATA_DIR = Path(__file__).parent / "sample_data"


class SampleProvider(DataProvider):
    id = "sample"
    name = "Offline sample snapshot"
    description = "Bundled snapshots of real filings (Microsoft, Apple, NVIDIA) for offline use and testing."
    requires = "Nothing"

    def _symbols(self) -> List[str]:
        return sorted(p.stem for p in DATA_DIR.glob("*.json"))

    def search(self, query: str, limit: int = 8) -> List[SearchResult]:
        q = query.strip().lower()
        out = []
        for sym in self._symbols():
            ds = self._load(sym)
            if q in sym.lower() or q in ds.profile.name.lower():
                out.append(SearchResult(sym, ds.profile.name, ds.profile.exchange))
        return out[:limit]

    def _load(self, symbol: str) -> FinancialDataset:
        p = DATA_DIR / f"{symbol.upper()}.json"
        if not p.exists():
            raise ProviderError(f"No offline snapshot for '{symbol}'. Available: {', '.join(self._symbols())}")
        ds = FinancialDataset.from_dict(json.loads(p.read_text()))
        ds.source = f"Offline snapshot of Yahoo Finance data retrieved {ds.retrieved_at[:10]}"
        return ds

    def fetch(self, symbol: str) -> FinancialDataset:
        return self._load(symbol)
