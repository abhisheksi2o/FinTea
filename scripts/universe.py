#!/usr/bin/env python3
"""Build data/universe.csv: the companies the static site pre-builds.

Sources (public constituent lists):
  India   - NSE: NIFTY Total Market (~750 companies, every significant listing on NSE)
  USA     - Wikipedia: S&P 500, NASDAQ-100
  UK      - Wikipedia: FTSE 100, FTSE 250
  Europe  - Wikipedia: EURO STOXX 50, DAX, CAC 40
  Japan   - Wikipedia: Nikkei 225
  HK      - Wikipedia: Hang Seng Index
  Canada  - Wikipedia: S&P/TSX 60
  Australia - Wikipedia: S&P/ASX 200
  Singapore - Wikipedia: Straits Times Index
  Korea   - Wikipedia: KOSPI 200

Each entry is converted to its Yahoo Finance symbol and (with --validate) checked against
Yahoo's chart endpoint, which also supplies the listed name and currency.

Usage: python scripts/universe.py [--validate] [--out data/universe.csv]
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0"}  # NSE and Yahoo reject longer, descriptive user agents
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

Row = Dict[str, str]


def get(url: str) -> str:
    last: Exception | None = None
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            return r.text
        except Exception as e:  # transient proxy / network hiccups
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def tables(url: str) -> List[pd.DataFrame]:
    return pd.read_html(io.StringIO(get(url)))


def find_table(url: str, must: List[str]) -> pd.DataFrame:
    for t in tables(url):
        cols = [str(c).lower() for c in t.columns]
        if all(any(m in c for c in cols) for m in must):
            return t
    raise RuntimeError(f"no table with {must} on {url}")


def col(t: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        for c in t.columns:
            if n.lower() in str(c).lower():
                return t[c].astype(str)
    raise KeyError(names)


def clean(s: str) -> str:
    s = re.sub(r"\[.*?\]", "", str(s)).strip()
    return s.replace("​", "")


# ---------------------------------------------------------------- sources
def nse_total_market() -> List[Row]:
    text = get("https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = r["Symbol"].strip()
        out.append({"symbol": f"{sym}.NS", "name": clean(r["Company Name"]), "country": "India",
                    "index": "NIFTY Total Market", "sector": clean(r.get("Industry", ""))})
    return out


def sp500() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", ["symbol", "security", "gics sector"])
    return [{"symbol": clean(s).replace(".", "-"), "name": clean(n), "country": "USA", "index": "S&P 500", "sector": clean(g)}
            for s, n, g in zip(col(t, "symbol"), col(t, "security"), col(t, "gics sector"))]


def nasdaq100() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/Nasdaq-100", ["ticker", "company", "gics sector"])
    return [{"symbol": clean(s).replace(".", "-"), "name": clean(n), "country": "USA", "index": "NASDAQ-100", "sector": clean(g)}
            for s, n, g in zip(col(t, "ticker", "symbol"), col(t, "company"), col(t, "gics sector"))]


def ftse(url: str, index: str) -> List[Row]:
    t = find_table(url, ["ticker", "company"])
    sector = col(t, "ftse industry", "sector") if any("sector" in str(c).lower() or "industry" in str(c).lower() for c in t.columns) else None
    out = []
    for i, (s, n) in enumerate(zip(col(t, "ticker"), col(t, "company"))):
        sym = clean(s).replace(".", "-").rstrip("-")
        out.append({"symbol": f"{sym}.L", "name": clean(n), "country": "UK", "index": index,
                    "sector": clean(sector.iloc[i]) if sector is not None else ""})
    return out


def dax() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/DAX", ["ticker", "company"])
    sector = col(t, "prime standard sector", "sector")
    out = []
    for s, n, g in zip(col(t, "ticker"), col(t, "company"), sector):
        sym = clean(s).upper()
        sym = sym if sym.endswith(".DE") else f"{sym}.DE"
        out.append({"symbol": sym, "name": clean(n), "country": "Germany", "index": "DAX", "sector": clean(g)})
    return out


def cac40() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/CAC_40", ["ticker", "company"])
    sector = col(t, "sector")
    out = []
    for s, n, g in zip(col(t, "ticker"), col(t, "company"), sector):
        sym = clean(s).upper()
        sym = sym if sym.endswith(".PA") else f"{sym}.PA"
        out.append({"symbol": sym, "name": clean(n), "country": "France", "index": "CAC 40", "sector": clean(g)})
    return out


def eurostoxx() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/EURO_STOXX_50", ["ticker", "name"])
    sector = col(t, "sector", "industry")
    return [{"symbol": clean(s).upper(), "name": clean(n), "country": "Eurozone", "index": "EURO STOXX 50", "sector": clean(g)}
            for s, n, g in zip(col(t, "ticker"), col(t, "name"), sector)]


def nikkei() -> List[Row]:
    """The Nikkei 225 article lists constituents as bullet items 'Company (TYO: 1234)'."""
    html = get("https://en.wikipedia.org/wiki/Nikkei_225")
    out = []
    for m in re.finditer(r"<li[^>]*>((?:(?!</li>).)*?)\(<a[^>]*>TYO</a>(?:(?!</li>).)*?>(\d{4})</a>", html, flags=re.S):
        name = clean(re.sub(r"<[^>]+>", "", m.group(1))).strip(" ,")
        if len(name) > 80 or "\n" in name:  # navigation noise; Yahoo's listed name replaces it during validation
            name = ""
        out.append({"symbol": f"{m.group(2)}.T", "name": name, "country": "Japan", "index": "Nikkei 225", "sector": ""})
    return out


def hang_seng() -> List[Row]:
    out = []
    for t in tables("https://en.wikipedia.org/wiki/Hang_Seng_Index"):
        cols = [str(c).lower() for c in t.columns]
        if not (any("ticker" in c or "code" in c or "stock" in c for c in cols) and any("name" in c or "company" in c for c in cols)):
            continue
        try:
            codes, names = col(t, "ticker", "code", "stock"), col(t, "name", "company")
        except KeyError:
            continue
        for s, n in zip(codes, names):
            code = re.sub(r"\D", "", clean(s))
            if 1 <= len(code) <= 5:
                out.append({"symbol": f"{int(code):04d}.HK", "name": clean(n), "country": "Hong Kong", "index": "Hang Seng", "sector": ""})
    return out


def tsx60() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/S%26P/TSX_60", ["symbol", "company"])
    sector = col(t, "sector")
    return [{"symbol": clean(s).replace(".", "-") + ".TO", "name": clean(n), "country": "Canada", "index": "S&P/TSX 60", "sector": clean(g)}
            for s, n, g in zip(col(t, "symbol"), col(t, "company"), sector)]


def asx200() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/S%26P/ASX_200", ["code", "company"])
    sector = col(t, "sector")
    return [{"symbol": clean(s).upper() + ".AX", "name": clean(n), "country": "Australia", "index": "S&P/ASX 200", "sector": clean(g)}
            for s, n, g in zip(col(t, "code"), col(t, "company"), sector)]


def sti() -> List[Row]:
    t = find_table("https://en.wikipedia.org/wiki/Straits_Times_Index", ["symbol", "company"])
    out = []
    for s, n in zip(col(t, "symbol"), col(t, "company")):
        sym = clean(s).split(":")[-1].strip().upper()
        out.append({"symbol": f"{sym}.SI", "name": clean(n), "country": "Singapore", "index": "Straits Times", "sector": ""})
    return out


def kospi200() -> List[Row]:
    out = []
    for t in tables("https://en.wikipedia.org/wiki/KOSPI_200"):
        cols = [str(c).lower() for c in t.columns]
        if any("ticker" in c or "code" in c or "symbol" in c for c in cols) and any("company" in c or "name" in c for c in cols):
            for s, n in zip(col(t, "ticker", "code", "symbol"), col(t, "company", "name")):
                code = re.sub(r"\D", "", clean(s))
                if len(code) == 6:
                    out.append({"symbol": f"{code}.KS", "name": clean(n), "country": "South Korea", "index": "KOSPI 200", "sector": ""})
    return out


SOURCES = [
    ("NIFTY Total Market", nse_total_market), ("S&P 500", sp500),
    ("FTSE 100", lambda: ftse("https://en.wikipedia.org/wiki/FTSE_100_Index", "FTSE 100")),
    ("FTSE 250", lambda: ftse("https://en.wikipedia.org/wiki/FTSE_250_Index", "FTSE 250")),
    ("EURO STOXX 50", eurostoxx), ("DAX", dax), ("CAC 40", cac40), ("Nikkei 225", nikkei), ("Hang Seng", hang_seng),
    ("S&P/TSX 60", tsx60), ("S&P/ASX 200", asx200), ("Straits Times", sti), ("KOSPI 200", kospi200),
]


def validate(rows: List[Row], sleep: float = 0.25) -> List[Row]:
    """Keep symbols Yahoo knows; fill name/currency/exchange from the chart metadata."""
    from fintea.providers.yahoo import YahooProvider
    y = YahooProvider()
    ok: List[Row] = []
    for i, r in enumerate(rows):
        try:
            meta = y._chart(r["symbol"], "5d", "1d")["meta"]
            if meta.get("instrumentType") not in ("EQUITY", None):
                raise ValueError(meta.get("instrumentType"))
            r["name"] = meta.get("longName") or meta.get("shortName") or r["name"]
            r["currency"] = meta.get("currency", "")
            r["exchange"] = meta.get("fullExchangeName", "")
            ok.append(r)
        except Exception as e:
            print(f"  drop {r['symbol']} ({r['name'][:30]}): {str(e)[:60]}", flush=True)
        if i % 100 == 0:
            print(f"  validated {i}/{len(rows)} ...", flush=True)
        time.sleep(sleep)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "universe.csv"))
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated subset of source names")
    args = ap.parse_args()
    rows: List[Row] = []
    seen: Dict[str, Row] = {}
    for name, fn in SOURCES:
        if args.only and name not in args.only.split(","):
            continue
        try:
            got = fn()
        except Exception as e:
            print(f"{name}: FAILED {e}", flush=True)
            continue
        new = 0
        for r in got:
            r["symbol"] = r["symbol"].strip().upper()
            if not r["symbol"] or r["symbol"].startswith("."):
                continue
            if r["symbol"] in seen:
                seen[r["symbol"]]["index"] += f"; {r['index']}"
                continue
            seen[r["symbol"]] = r
            rows.append(r)
            new += 1
        print(f"{name}: {len(got)} rows, {new} new", flush=True)
    if args.validate:
        rows = validate(rows)
    for r in rows:
        r.setdefault("currency", ""); r.setdefault("exchange", "")
    rows.sort(key=lambda r: (r["country"], r["symbol"]))
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "name", "country", "index", "sector", "currency", "exchange"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} companies to {args.out}")


if __name__ == "__main__":
    main()
