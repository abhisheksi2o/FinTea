"""Orchestration for default-risk analyses: fetch data -> derive inputs -> build book -> write, verify and stamp the xlsx."""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .. import config
from ..excel import verify_workbook, write_workbook
from ..providers import FinancialDataset, load_dataset
from .builder import RiskResult, build_risk_model, stamp_verification
from .inputs import derive_inputs


@dataclass
class StoredRisk:
    id: str
    result: RiskResult
    xlsx: bytes
    verification: Dict[str, Any]
    recalculated: Optional[bytes]
    provider: str
    created: float = field(default_factory=time.time)

    def payload(self, include_sheets: bool = True) -> Dict[str, Any]:
        r = self.result
        ver = {k: v for k, v in self.verification.items() if k != "recalculated"}
        out: Dict[str, Any] = {
            "id": self.id, "provider": self.provider, "kind": "risk", "summary": r.summary, "inputs": r.inputs.to_json(),
            "feedback": r.feedback, "verification": ver, "meta": r.book.meta, "merton": r.merton,
            "download_url": f"/api/risk/{self.id}/download",
        }
        if include_sheets:
            js = r.book.to_json()
            out["sheets"] = js["sheets"]
            out["charts"] = [c for s in js["sheets"] for c in s.get("charts", [])]
        return out


class RiskService:
    def __init__(self):
        self._items: "OrderedDict[str, StoredRisk]" = OrderedDict()
        self._datasets: Dict[str, tuple[float, FinancialDataset]] = {}
        self._lock = threading.Lock()

    def dataset(self, query: str, provider: str) -> FinancialDataset:
        key = f"{provider}:{query.strip().upper()}"
        with self._lock:
            hit = self._datasets.get(key)
            if hit and time.time() - hit[0] < config.DATASET_TTL_SECONDS:
                return hit[1]
        # the risk analysis does not need a five-year beta history, so accept recently (re)listed companies
        ds = load_dataset(query, provider, require_history=False)
        with self._lock:
            self._datasets[key] = (time.time(), ds)
            self._datasets[f"{provider}:{ds.profile.symbol.upper()}"] = (time.time(), ds)
        return ds

    def build(self, query: str, provider: str = config.DEFAULT_PROVIDER, overrides: Optional[Dict[str, Any]] = None,
              verify: bool = True) -> StoredRisk:
        ds = self.dataset(query, provider)
        return self._build(ds, provider, overrides, verify)

    def rebuild(self, risk_id: str, overrides: Optional[Dict[str, Any]] = None, verify: bool = True) -> StoredRisk:
        base = self.get(risk_id)
        merged: Dict[str, Any] = {k: base.result.inputs.values[k] for k in base.result.inputs.overridden}
        merged.update(overrides or {})
        return self._build(base.result.dataset, base.provider, merged, verify)

    def _build(self, ds: FinancialDataset, provider: str, overrides, verify: bool) -> StoredRisk:
        inputs = derive_inputs(ds, overrides)
        result = build_risk_model(ds, inputs)
        xlsx = write_workbook(result.book)
        verification: Dict[str, Any] = {"status": "skipped", "reason": "verification disabled", "cells_checked": 0, "mismatches": []}
        recalculated = None
        if verify and config.VERIFY_WITH_LIBREOFFICE:
            verification = verify_workbook(result.book, xlsx)
            recalculated = verification.pop("recalculated", None)
        stamp_verification(result, verification)     # text only; formulas unchanged, so the verification still holds
        xlsx = write_workbook(result.book)
        stored = StoredRisk(id=uuid.uuid4().hex[:12], result=result, xlsx=xlsx, verification=verification,
                            recalculated=recalculated, provider=provider)
        with self._lock:
            self._items[stored.id] = stored
            while len(self._items) > config.MODEL_CACHE_SIZE:
                self._items.popitem(last=False)
        return stored

    def get(self, risk_id: str) -> StoredRisk:
        with self._lock:
            m = self._items.get(risk_id)
        if m is None:
            raise KeyError(risk_id)
        return m


risk_service = RiskService()
