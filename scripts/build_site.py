#!/usr/bin/env python3
"""Build the static FinTea site (GitHub Pages): pre-built models + the static frontend.

Two phases so the work can be sharded across parallel CI runners:

  build   python scripts/build_site.py --out site --shard 3/10
          Builds every company of shard 3 (of 10) from data/universe.csv: fetches live data,
          builds the model, verifies a sample with LibreOffice, and writes
          site/models/{SYMBOL}.json.gz plus site/shards/3.json (index entries + failures).

  merge   python scripts/build_site.py --out site --merge --frontend-dist frontend/dist
          Combines site/shards/*.json into site/index.json and copies the static frontend in.

Running without --shard/--merge does both for the whole universe (or --tickers) in one go.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fintea.excel import verify_workbook, write_workbook  # noqa: E402
from fintea.model import build_model  # noqa: E402
from fintea.providers import get_provider, load_dataset, normalize  # noqa: E402

UNIVERSE = ROOT / "data" / "universe.csv"
FINANCIAL_WORDS = ("bank", "financ", "insur", "capital market", "reit", "real estate investment", "asset management",
                   "brokerage", "stock exchange", "lending", "mortgage", "nbfc")


def is_financial(sector: str, industry: str = "") -> bool:
    text = f"{sector} {industry}".lower()
    return any(w in text for w in FINANCIAL_WORDS)


def load_universe(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def should_verify(symbol: str, fraction: float) -> bool:
    if fraction >= 1:
        return True
    if fraction <= 0:
        return False
    h = int(hashlib.sha1(symbol.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return h < fraction


def fetch_dataset(symbol: str, provider_id: str):
    """Fetch by exact symbol (no name search, so bulk builds never resolve to the wrong company)."""
    p = get_provider(provider_id)
    return normalize(p.fetch(symbol)), provider_id


def build_one(row: Dict[str, str], provider: str, years: int, verify: bool):
    symbol = row["symbol"]
    try:
        ds, used = fetch_dataset(symbol, provider)
    except Exception as e:
        if provider != "sample":
            print(f"  live fetch failed ({str(e)[:100]}); trying snapshot", flush=True)
            ds, used = fetch_dataset(symbol, "sample")
        else:
            raise
    if row.get("sector") and not ds.profile.sector:
        ds.profile.sector = row["sector"]
    if row.get("country") and not ds.profile.country:
        ds.profile.country = row["country"]
    financial = is_financial(ds.profile.sector, ds.profile.industry)
    if financial:
        ds.notes.append("Sector classified as financial services: a free-cash-flow-to-firm DCF is not the right tool for banks, "
                        "insurers or REITs (their debt is operating, not financing). Treat the valuation as indicative only.")
    res = build_model(ds, years=years)
    if res.summary.get("implied_price") is None or res.summary.get("error_cells"):
        raise ValueError(f"model has error cells: {res.summary.get('error_cells')} (e.g. zero shares, missing statements)")
    ver: Dict[str, Any] = {"status": "skipped", "reason": "sampled verification (this company was not in the sample)", "cells_checked": 0, "mismatches": []}
    if verify:
        xlsx = write_workbook(res.book)
        ver = verify_workbook(res.book, xlsx)
        ver.pop("recalculated", None)
    payload = {
        "id": symbol.replace(".", "_"), "provider": used, "summary": res.summary,
        "assumptions": res.assumptions.to_json(), "feedback": res.feedback, "verification": ver,
        "meta": res.book.meta, "llm": None, "download_url": "", "client_generated": True,
        "sheets": res.book.to_json()["sheets"], "static": True,
        "listing": {"country": row.get("country", ""), "index": row.get("index", ""), "sector": ds.profile.sector,
                    "financial": financial},
    }
    entry = {"symbol": res.summary["symbol"], "name": res.summary["company"], "country": row.get("country", ""),
             "index": row.get("index", ""), "sector": ds.profile.sector, "financial": financial,
             "currency": res.summary["currency"], "price": res.summary["price"], "implied_price": res.summary["implied_price"],
             "upside": res.summary["upside"], "wacc": res.summary["wacc"], "status": res.summary["overall_status"],
             "verification": ver["status"], "cells_checked": ver.get("cells_checked", 0), "provider": used,
             "generated": res.book.meta["generated"], "json": f"models/{symbol}.json.gz"}
    return payload, entry


def build_shard(rows: List[Dict[str, str]], out: Path, provider: str, years: int, verify_fraction: float, sleep: float,
                shard_name: str) -> None:
    models = out / "models"
    models.mkdir(parents=True, exist_ok=True)
    (out / "shards").mkdir(parents=True, exist_ok=True)
    index, failures = [], []
    t_start = time.time()
    for i, row in enumerate(rows, start=1):
        sym = row["symbol"]
        t0 = time.time()
        try:
            payload, entry = build_one(row, provider, years, should_verify(sym, verify_fraction))
        except Exception as e:
            print(f"[{i}/{len(rows)}] {sym}: FAILED {str(e)[:160]}", flush=True)
            failures.append({"symbol": sym, "name": row.get("name", ""), "error": str(e)[:200]})
            continue
        with gzip.open(models / f"{sym}.json.gz", "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(payload, f, separators=(",", ":"), default=str)
        index.append(entry)
        print(f"[{i}/{len(rows)}] {sym}: implied {entry['implied_price']:,.2f} vs {entry['price']:,.2f} {entry['currency']}, "
              f"{entry['verification']} in {time.time() - t0:.1f}s", flush=True)
        if entry["verification"] == "mismatch":
            print(f"  VERIFICATION MISMATCH: {json.dumps(payload['verification'].get('mismatches', [])[:3])[:600]}", flush=True)
        if provider != "sample":
            time.sleep(sleep)
    (out / "shards" / f"{shard_name}.json").write_text(json.dumps({"models": index, "failures": failures}, default=str))
    print(f"shard {shard_name}: {len(index)} built, {len(failures)} failed in {(time.time() - t_start) / 60:.1f} min", flush=True)


def merge(out: Path, frontend_dist: Optional[Path]) -> int:
    index, failures = [], []
    for p in sorted((out / "shards").glob("*.json")):
        d = json.loads(p.read_text())
        index.extend(d["models"])
        failures.extend(d["failures"])
    seen = set()
    dedup = []
    for m in sorted(index, key=lambda m: (m["country"], m["symbol"])):
        if m["symbol"] not in seen:
            seen.add(m["symbol"])
            dedup.append(m)
    countries = sorted({m["country"] for m in dedup})
    indices = sorted({i.strip() for m in dedup for i in m["index"].split(";") if i.strip()})
    (out / "index.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "count": len(dedup),
        "countries": countries, "indices": indices, "models": dedup, "failures": failures}, separators=(",", ":")))
    if frontend_dist and frontend_dist.exists():
        for item in frontend_dist.iterdir():
            dest = out / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        print(f"copied frontend from {frontend_dist}")
    (out / ".nojekyll").write_text("")
    print(f"merged: {len(dedup)} models, {len(failures)} failures -> {out / 'index.json'}")
    return len(dedup)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--universe", default=str(UNIVERSE))
    ap.add_argument("--tickers", default="", help="comma-separated symbols instead of the universe file")
    ap.add_argument("--shard", default="", help="i/n: build only the i-th of n shards")
    ap.add_argument("--merge", action="store_true", help="merge shard indexes and copy the frontend")
    ap.add_argument("--frontend-dist", default="")
    ap.add_argument("--provider", default="yahoo")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--verify-fraction", type=float, default=0.1, help="share of companies verified with LibreOffice")
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between live fetches (rate limits)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out)
    if args.merge:
        n = merge(out, Path(args.frontend_dist) if args.frontend_dist else None)
        sys.exit(0 if n else 1)
    if args.tickers:
        rows = [{"symbol": t.strip(), "name": "", "country": "", "index": "", "sector": ""} for t in args.tickers.split(",") if t.strip()]
    else:
        rows = load_universe(Path(args.universe))
    shard_name = "all"
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        rows = [r for k, r in enumerate(rows) if k % n == i]
        shard_name = str(i)
    if args.limit:
        rows = rows[: args.limit]
    build_shard(rows, out, args.provider, args.years, args.verify_fraction, args.sleep, shard_name)
    if not args.shard:
        merge(out, Path(args.frontend_dist) if args.frontend_dist else None)


if __name__ == "__main__":
    main()
