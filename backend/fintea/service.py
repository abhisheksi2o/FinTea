"""Orchestration: fetch data -> derive assumptions -> build book -> write & verify xlsx."""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import config
from .excel import verify_workbook, write_workbook
from .model import ModelResult, build_model, derive_assumptions
from .providers import FinancialDataset, load_dataset
from .providers.base import ProviderError


@dataclass
class StoredModel:
    id: str
    result: ModelResult
    xlsx: bytes
    verification: Dict[str, Any]
    recalculated: Optional[bytes]
    provider: str
    created: float = field(default_factory=time.time)
    llm: Optional[Dict[str, Any]] = None

    def payload(self, include_sheets: bool = True) -> Dict[str, Any]:
        r = self.result
        ver = {k: v for k, v in self.verification.items() if k != "recalculated"}
        out = {
            "id": self.id, "provider": self.provider, "summary": r.summary,
            "assumptions": r.assumptions.to_json(), "feedback": r.feedback, "verification": ver,
            "meta": r.book.meta, "llm": self.llm,
            "download_url": f"/api/models/{self.id}/download",
        }
        if include_sheets:
            out["sheets"] = r.book.to_json()["sheets"]
        return out


class ModelService:
    def __init__(self):
        self._models: "OrderedDict[str, StoredModel]" = OrderedDict()
        self._datasets: Dict[str, tuple[float, FinancialDataset]] = {}
        self._lock = threading.Lock()

    # -- datasets --------------------------------------------------------------
    def dataset(self, query: str, provider: str) -> FinancialDataset:
        key = f"{provider}:{query.strip().upper()}"
        with self._lock:
            hit = self._datasets.get(key)
            if hit and time.time() - hit[0] < config.DATASET_TTL_SECONDS:
                return hit[1]
        ds = load_dataset(query, provider)
        with self._lock:
            self._datasets[key] = (time.time(), ds)
            self._datasets[f"{provider}:{ds.profile.symbol.upper()}"] = (time.time(), ds)
        return ds

    # -- models ----------------------------------------------------------------
    def build(self, query: str, provider: str = config.DEFAULT_PROVIDER, years: int = 5,
              overrides: Optional[Dict[str, Any]] = None, verify: bool = True, llm: bool = True) -> StoredModel:
        ds = self.dataset(query, provider)
        return self._build_from_dataset(ds, provider, years, overrides, verify, llm)

    def rebuild(self, model_id: str, years: Optional[int] = None, overrides: Optional[Dict[str, Any]] = None,
                verify: bool = True, llm: bool = True) -> StoredModel:
        base = self.get(model_id)
        ds = base.result.dataset
        years = years or base.result.assumptions.years
        merged: Dict[str, Any] = {}
        # keep earlier user overrides unless replaced
        for k in base.result.assumptions.overridden:
            merged[k] = base.result.assumptions.values[k]
        merged.update(overrides or {})
        return self._build_from_dataset(ds, base.provider, years, merged, verify, llm)

    def _build_from_dataset(self, ds: FinancialDataset, provider: str, years: int, overrides, verify: bool, llm: bool) -> StoredModel:
        assumptions = derive_assumptions(ds, years, overrides)
        result = build_model(ds, assumptions)
        xlsx = write_workbook(result.book)
        verification: Dict[str, Any] = {"status": "skipped", "reason": "verification disabled", "cells_checked": 0, "mismatches": []}
        recalculated = None
        if verify and config.VERIFY_WITH_LIBREOFFICE:
            verification = verify_workbook(result.book, xlsx)
            recalculated = verification.pop("recalculated", None)
        stored = StoredModel(id=uuid.uuid4().hex[:12], result=result, xlsx=xlsx, verification=verification,
                             recalculated=recalculated, provider=provider)
        if llm and config.LLM_ENABLED:
            try:
                from .model.llm import ai_commentary
                stored.llm = ai_commentary(result)
            except Exception as e:  # never fail a build because of the optional commentary
                stored.llm = {"status": "error", "error": str(e)[:300]}
        with self._lock:
            self._models[stored.id] = stored
            while len(self._models) > config.MODEL_CACHE_SIZE:
                self._models.popitem(last=False)
        return stored

    def get(self, model_id: str) -> StoredModel:
        with self._lock:
            m = self._models.get(model_id)
        if m is None:
            raise KeyError(model_id)
        return m


service = ModelService()
