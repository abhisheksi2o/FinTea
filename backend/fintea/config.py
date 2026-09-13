"""Runtime configuration from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

VERIFY_WITH_LIBREOFFICE = os.environ.get("FINTEA_VERIFY", "1") == "1"
MODEL_CACHE_SIZE = int(os.environ.get("FINTEA_CACHE_SIZE", "200"))
DATASET_TTL_SECONDS = int(os.environ.get("FINTEA_DATASET_TTL", "3600"))
DEFAULT_PROVIDER = os.environ.get("FINTEA_DEFAULT_PROVIDER", "yahoo")
FRONTEND_DIST = Path(os.environ.get("FINTEA_FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
LLM_MODEL = os.environ.get("FINTEA_LLM_MODEL", "claude-opus-5")
LLM_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY"))
