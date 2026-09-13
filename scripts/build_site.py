#!/usr/bin/env python3
"""Build the static FinTea site (GitHub Pages): pre-built models + the static frontend.

Usage: python scripts/build_site.py --out site [--frontend-dist frontend/dist] [--tickers AAPL,MSFT] [--provider yahoo]

For every ticker the model is built from live data (default provider), falling back to the
bundled snapshot when the live source fails, then written as JSON (full payload with sheets)
and as a verified .xlsx. An index.json lists what was built.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fintea.excel import verify_workbook, write_workbook  # noqa: E402
from fintea.model import build_model  # noqa: E402
from fintea.providers import load_dataset  # noqa: E402

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL", "ADBE", "CRM", "NFLX", "AMD", "INTC",
    "CSCO", "QCOM", "WMT", "COST", "HD", "MCD", "NKE", "KO", "PEP", "PG", "JNJ", "LLY", "MRK", "PFE", "ABBV", "UNH",
    "XOM", "CVX", "CAT", "BA", "HON", "GE", "UPS", "DIS", "T", "VZ",
    "INFY.NS", "TCS.NS", "RELIANCE.NS", "ASML", "SAP", "NESN.SW", "TM", "SONY", "SHEL.L", "AZN.L", "ULVR.L", "TSM", "BABA",
]


def build_one(symbol: str, provider: str, years: int, verify: bool):
    try:
        ds = load_dataset(symbol, provider)
        used = provider
    except Exception as e:  # live source failed -> snapshot
        print(f"  live fetch failed ({str(e)[:120]}); trying snapshot", flush=True)
        ds = load_dataset(symbol, "sample")
        used = "sample"
    res = build_model(ds, years=years)
    xlsx = write_workbook(res.book)
    ver = {"status": "skipped", "reason": "verification disabled", "cells_checked": 0, "mismatches": []}
    if verify:
        ver = verify_workbook(res.book, xlsx)
        ver.pop("recalculated", None)
    payload = {
        "id": symbol.replace(".", "_"), "provider": used, "summary": res.summary,
        "assumptions": res.assumptions.to_json(), "feedback": res.feedback, "verification": ver,
        "meta": res.book.meta, "llm": None, "download_url": f"models/{symbol}.xlsx",
        "sheets": res.book.to_json()["sheets"], "static": True,
    }
    return payload, xlsx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--frontend-dist", default="frontend/dist")
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--provider", default="yahoo")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.5, help="pause between live fetches (rate limits)")
    args = ap.parse_args()
    out = Path(args.out)
    models = out / "models"
    models.mkdir(parents=True, exist_ok=True)
    index = []
    failures = []
    for sym in [t.strip() for t in args.tickers.split(",") if t.strip()]:
        t0 = time.time()
        print(f"building {sym} ...", flush=True)
        try:
            payload, xlsx = build_one(sym, args.provider, args.years, not args.no_verify)
        except Exception as e:
            print(f"  FAILED: {e}", flush=True)
            failures.append({"symbol": sym, "error": str(e)[:200]})
            continue
        (models / f"{sym}.json").write_text(json.dumps(payload, separators=(",", ":"), default=str))
        (models / f"{sym}.xlsx").write_bytes(xlsx)
        s = payload["summary"]
        index.append({"symbol": s["symbol"], "name": s["company"], "exchange": payload["meta"].get("symbol", ""),
                      "currency": s["currency"], "price": s["price"], "implied_price": s["implied_price"],
                      "upside": s["upside"], "wacc": s["wacc"], "status": s["overall_status"],
                      "verification": payload["verification"]["status"], "cells_checked": payload["verification"]["cells_checked"],
                      "provider": payload["provider"], "generated": payload["meta"]["generated"], "json": f"models/{sym}.json",
                      "xlsx": f"models/{sym}.xlsx"})
        print(f"  ok: implied {s['implied_price']:.2f} vs {s['price']:.2f}, verification {payload['verification']['status']} "
              f"({payload['verification']['cells_checked']} cells) in {time.time() - t0:.1f}s", flush=True)
        if args.provider != "sample":
            time.sleep(args.sleep)
    (out / "index.json").write_text(json.dumps({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                                "models": index, "failures": failures}, indent=1))
    dist = Path(args.frontend_dist)
    if dist.exists():
        for item in dist.iterdir():
            dest = out / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        print(f"copied frontend from {dist}")
    (out / ".nojekyll").write_text("")
    print(f"done: {len(index)} models, {len(failures)} failures -> {out}")
    if not index:
        sys.exit(1)


if __name__ == "__main__":
    main()
