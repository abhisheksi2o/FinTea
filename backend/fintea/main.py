"""FinTea API entry point. Run with: uvicorn fintea.main:app --reload"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from .api.routes import router

app = FastAPI(title="FinTea", version=__version__,
              description="Formula-driven financial model builder: type a company, download a fully linked Excel model.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

dist = config.FRONTEND_DIST
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(dist / "index.html")
