from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config
from ..excel import soffice_available
from ..providers import get_provider, list_providers
from ..providers.base import ProviderError
from ..service import service

router = APIRouter(prefix="/api")


class BuildRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=80, description="Company name or ticker")
    provider: str = Field(config.DEFAULT_PROVIDER)
    years: int = Field(5, ge=3, le=10)
    overrides: Dict[str, Any] = Field(default_factory=dict)
    verify: bool = True
    include_sheets: bool = True


class RebuildRequest(BaseModel):
    years: Optional[int] = Field(None, ge=3, le=10)
    overrides: Dict[str, Any] = Field(default_factory=dict)
    verify: bool = True
    include_sheets: bool = True


@router.get("/health")
def health():
    return {"status": "ok", "libreoffice": soffice_available(), "verify_enabled": config.VERIFY_WITH_LIBREOFFICE,
            "llm_enabled": config.LLM_ENABLED}


@router.get("/providers")
def providers():
    return {"providers": list_providers(), "default": config.DEFAULT_PROVIDER}


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=80), provider: str = config.DEFAULT_PROVIDER, limit: int = 8):
    try:
        p = get_provider(provider)
        return {"results": [r.__dict__ for r in p.search(q, limit=limit)]}
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/models")
def build(req: BuildRequest):
    try:
        m = service.build(req.query, req.provider, req.years, req.overrides, req.verify)
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return m.payload(req.include_sheets)


@router.post("/models/{model_id}/rebuild")
def rebuild(model_id: str, req: RebuildRequest):
    try:
        m = service.rebuild(model_id, req.years, req.overrides, req.verify)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found (it may have expired); build it again")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return m.payload(req.include_sheets)


@router.get("/models/{model_id}")
def get_model(model_id: str, include_sheets: bool = True):
    try:
        return service.get(model_id).payload(include_sheets)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found")


@router.get("/models/{model_id}/download")
def download(model_id: str, recalculated: bool = False):
    try:
        m = service.get(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found")
    data = m.recalculated if (recalculated and m.recalculated) else m.xlsx
    sym = re.sub(r"[^A-Za-z0-9._-]", "_", m.result.dataset.profile.symbol)
    fname = f"FinTea_{sym}_model_{m.result.summary['base_year']}.xlsx"
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
