#!/usr/bin/env python3
"""Generate Jekyll stock-movers data from Yahoo Finance.

Supports a two-phase workflow to keep daily runs fast:

1. Cache refresh (weekly): ``--refresh-cache`` downloads the full
   Nasdaq-listed + S&P 500 universe, classifies every ticker for tech
   relevance, uses yfinance profile lookups for borderline cases, and writes a
   compact JSON cache to ``--cache-path``.

2. Daily run (default): loads a fresh pre-filtered tech ticker cache so only
   the tech universe needs price data. If the cache is missing or stale, the
   script falls back to the full universe automatically.

After the scheduled agent researches catalysts, run the script again with
``--input`` and ``--explanations`` to merge AI-written explanations without
refetching prices.
"""

from __future__ import annotations

import argparse
import csv
import html.parser
import io
import json
import math
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
SP500_CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "TechBriefingMarketMovers/1.0"
DEFAULT_BATCH_SIZE = 200
TECH_TICKER_ALLOWLIST = {
    "AAPL",
    "ABNB",
    "ADBE",
    "ADI",
    "AMD",
    "AMAT",
    "AMZN",
    "ANSS",
    "APP",
    "ARM",
    "ASML",
    "AVGO",
    "CDNS",
    "COIN",
    "CRM",
    "CRWD",
    "CSCO",
    "DASH",
    "DDOG",
    "FICO",
    "FTNT",
    "GOOGL",
    "HOOD",
    "HUBS",
    "INTC",
    "INTU",
    "KLAC",
    "LCID",
    "LRCX",
    "LYFT",
    "MDB",
    "MELI",
    "META",
    "MRVL",
    "MSFT",
    "MSTR",
    "MU",
    "NET",
    "NFLX",
    "NOW",
    "NVDA",
    "NXPI",
    "ON",
    "ORCL",
    "PANW",
    "PINS",
    "PLTR",
    "QCOM",
    "RBLX",
    "RIVN",
    "ROKU",
    "SE",
    "SMCI",
    "SNAP",
    "SNOW",
    "SNPS",
    "SHOP",
    "TEAM",
    "TSLA",
    "TTD",
    "TXN",
    "U",
    "UBER",
    "VEEV",
    "WDAY",
    "XYZ",
    "ZS",
}
ISSUE_NAME_EXCLUSIONS = re.compile(
    r"\b("
    r"acquisition right|"
    r"closed end|"
    r"depositary|"
    r"etf|"
    r"etn|"
    r"exchange traded|"
    r"fund|"
    r"notes? due|"
    r"preferred|"
    r"preference|"
    r"right|"
    r"rights|"
    r"unit|"
    r"units|"
    r"warrant|"
    r"warrants"
    r")\b",
    re.IGNORECASE,
)
NON_TECH_NAME_EXCLUSIONS = re.compile(
    r"\b("
    r"biopharma|"
    r"biopharmaceutical|"
    r"biotech|"
    r"biotechnology|"
    r"biosciences?|"
    r"clinical|"
    r"diagnostics?|"
    r"genomics?|"
    r"health|"
    r"healthcare|"
    r"immuno|"
    r"medical|"
    r"oncology|"
    r"pharma|"
    r"pharmaceutical|"
    r"therapeutics?"
    r")\b",
    re.IGNORECASE,
)
TECH_KEYWORDS = re.compile(
    r"\b("
    r"3d printing|"
    r"ai|"
    r"analytics?|"
    r"application software|"
    r"artificial intelligence|"
    r"automation|"
    r"autonomous|"
    r"broadline retail|"
    r"cloud|"
    r"communications equipment|"
    r"computer|"
    r"consumer electronics|"
    r"cyber|"
    r"cybersecurity|"
    r"data|"
    r"digital|"
    r"e-commerce|"
    r"electric vehicle|"
    r"electronic components?|"
    r"electronic equipment|"
    r"fintech|"
    r"hardware|"
    r"information technology|"
    r"interactive media|"
    r"internet|"
    r"it consulting|"
    r"machine learning|"
    r"network|"
    r"online|"
    r"payments?|"
    r"platform|"
    r"robotics?|"
    r"saas|"
    r"semiconductor|"
    r"software|"
    r"systems software|"
    r"technology|"
    r"technologies|"
    r"telecom|"
    r"video games?"
    r")\b",
    re.IGNORECASE,
)


class SP500TableParser(html.parser.HTMLParser):
    """Small parser for Wikipedia's constituents table.

    Keeping this standard-library only avoids pulling in pandas just to read a
    single table. yfinance still installs pandas for price downloads.
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_constituents_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "constituents":
            self.in_constituents_table = True
        if not self.in_constituents_table:
            return
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif tag in {"th", "td"} and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_constituents_table:
            return
        if tag in {"th", "td"} and self.in_cell:
            text = " ".join("".join(self.current_cell).split())
            self.current_row.append(text)
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "table":
            self.in_constituents_table = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="_data/stock_movers.json",
        help="Path for the Jekyll JSON data file.",
    )
    parser.add_argument(
        "--input",
        help="Existing stock_movers JSON to reuse before merging explanations.",
    )
    parser.add_argument(
        "--explanations",
        help="JSON object or stock list containing ticker-to-explanation values.",
    )
    parser.add_argument("--count", type=int, default=15, help="Number of movers to publish.")
    parser.add_argument("--date", help="Trading date to write into the JSON payload.")
    parser.add_argument(
        "--data-as-of",
        help='Display timestamp, for example "2026-05-21, 9:00 AM CT".',
    )
    parser.add_argument(
        "--timezone",
        default="America/Chicago",
        help="Timezone used for generated_at and default display timestamps.",
    )
    parser.add_argument(
        "--tickers",
        help=(
            "Optional comma- or space-separated ticker list for testing. "
            "Defaults to Nasdaq-listed common stocks plus S&P 500 constituents."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of tickers per yfinance download request.",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=0,
        help="Optional minimum latest price filter. Defaults to no price filter.",
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=0,
        help="Optional minimum latest volume filter. Defaults to no volume filter.",
    )
    parser.add_argument(
        "--list-universe",
        action="store_true",
        help="Download and print universe counts without fetching prices.",
    )
    parser.add_argument(
        "--cache-path",
        default="_data/tech_ticker_cache.json",
        help="Path for the pre-filtered tech ticker cache file.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help=(
            "Download the full Nasdaq + S&P 500 universe, classify every ticker "
            "for tech relevance, and write the filtered list to --cache-path. "
            "Does not fetch prices or produce movers output."
        ),
    )
    parser.add_argument(
        "--cache-max-age-days",
        type=int,
        default=7,
        help="Maximum age in days before the ticker cache is considered stale.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the ticker cache and always download the full universe.",
    )
    parser.add_argument(
        "--max-cache-profile-lookups",
        type=int,
        default=750,
        help="Maximum yfinance profile lookups used while refreshing the ticker cache.",
    )
    parser.add_argument(
        "--include-non-tech",
        action="store_true",
        help="Publish the largest movers regardless of tech classification.",
    )
    parser.add_argument(
        "--max-sector-lookups",
        type=int,
        default=75,
        help="Maximum yfinance profile lookups used to classify borderline movers.",
    )
    return parser.parse_args()


def market_now(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone))


def display_time(now: datetime) -> str:
    time_text = now.strftime("%I:%M %p").lstrip("0")
    return f"{now.date().isoformat()}, {time_text} CT"


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def format_volume(value: Any) -> str:
    number = finite_number(value)
    if number is None:
        return ""
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if abs_number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if abs_number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(int(number))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = None
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise RuntimeError(f"Could not download {url}: {exc}") from exc
        with urllib.request.urlopen(
            request,
            timeout=30,
            context=ssl._create_unverified_context(),
        ) as response:
            return response.read().decode("utf-8", errors="replace")


def normalize_yahoo_ticker(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def clean_name(name: str) -> str:
    return " ".join(name.replace(" Common Stock", "").split())


def is_common_stock(symbol: str, security_name: str) -> bool:
    if not symbol or "$" in symbol or "^" in symbol or "/" in symbol:
        return False
    if ISSUE_NAME_EXCLUSIONS.search(security_name):
        return False
    return True


def make_stock_meta(
    name: str,
    source: str,
    sector: str = "",
    industry: str = "",
    force_tech: bool = False,
) -> dict[str, str]:
    return {
        "name": clean_name(name),
        "source": source,
        "sector": sector,
        "industry": industry,
        "force_tech": "true" if force_tech else "",
    }


def parse_ticker_override(raw: str | None) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    normalized = raw.replace(",", " ")
    tickers = [normalize_yahoo_ticker(ticker) for ticker in normalized.split() if ticker.strip()]
    return {
        ticker: make_stock_meta(ticker, source="manual", force_tech=True)
        for ticker in dict.fromkeys(tickers)
    }


def load_nasdaq_listed_common_stocks() -> dict[str, dict[str, str]]:
    text = fetch_text(NASDAQ_LISTED_URL)
    rows = csv.DictReader(io.StringIO(text), delimiter="|")
    stocks: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = (row.get("Symbol") or "").strip()
        if symbol == "File Creation Time":
            break
        security_name = (row.get("Security Name") or "").strip()
        if row.get("Test Issue") != "N":
            continue
        if row.get("ETF") == "Y" or row.get("NextShares") == "Y":
            continue
        if not is_common_stock(symbol, security_name):
            continue
        ticker = normalize_yahoo_ticker(symbol)
        stocks[ticker] = make_stock_meta(security_name or ticker, source="nasdaq_listed")
    return stocks


def load_sp500_constituents() -> dict[str, dict[str, str]]:
    parser = SP500TableParser()
    parser.feed(fetch_text(SP500_CONSTITUENTS_URL))
    if not parser.rows:
        raise RuntimeError("Could not find S&P 500 constituents table")

    header = parser.rows[0]
    try:
        symbol_index = header.index("Symbol")
        name_index = header.index("Security")
        sector_index = header.index("GICS Sector")
        industry_index = header.index("GICS Sub-Industry")
    except ValueError as exc:
        raise RuntimeError("Could not parse S&P 500 constituents table headers") from exc

    stocks: dict[str, dict[str, str]] = {}
    for row in parser.rows[1:]:
        if len(row) <= max(symbol_index, name_index, sector_index, industry_index):
            continue
        ticker = normalize_yahoo_ticker(row[symbol_index])
        stocks[ticker] = make_stock_meta(
            name=row[name_index] or ticker,
            source="sp500",
            sector=row[sector_index],
            industry=row[industry_index],
        )
    return stocks


def merge_stock_meta(
    existing: dict[str, str] | None,
    incoming: dict[str, str],
) -> dict[str, str]:
    if not existing:
        return dict(incoming)
    merged = dict(existing)
    for key in ("name", "sector", "industry"):
        if incoming.get(key):
            merged[key] = incoming[key]
    sources = {
        source
        for source in f"{existing.get('source', '')},{incoming.get('source', '')}".split(",")
        if source
    }
    merged["source"] = ",".join(sorted(sources))
    return merged


def load_market_universe() -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    nasdaq = load_nasdaq_listed_common_stocks()
    sp500 = load_sp500_constituents()
    combined = dict(nasdaq)
    for ticker, meta in sp500.items():
        combined[ticker] = merge_stock_meta(combined.get(ticker), meta)
    meta = {
        "mode": "nasdaq_listed_plus_sp500",
        "count": len(combined),
        "nasdaq_listed_common_stock_count": len(nasdaq),
        "sp500_count": len(sp500),
        "sources": [
            NASDAQ_LISTED_URL,
            SP500_CONSTITUENTS_URL,
        ],
    }
    return combined, meta


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_explanations(path: str | None) -> dict[str, str]:
    data = load_json(path)
    if not data:
        return {}
    if isinstance(data, dict) and "stocks" in data:
        rows = data.get("stocks") or []
        return {
            str(row.get("ticker", "")).upper(): str(row.get("explanation", "")).strip()
            for row in rows
            if row.get("ticker") and row.get("explanation")
        }
    return {
        str(ticker).upper(): str(explanation).strip()
        for ticker, explanation in data.items()
        if explanation
    }


def first_existing_column(frame: Any, names: list[str]) -> Any:
    for name in names:
        if name in frame:
            return frame[name]
    raise KeyError(names[0])


def extract_frame(download: Any, ticker: str, multi_ticker: bool) -> Any:
    if multi_ticker:
        return download[ticker]
    return download


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def fetch_price_rows(
    ticker_meta: dict[str, dict[str, str]],
    batch_size: int,
    min_price: float,
    min_volume: int,
) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit(
            "yfinance is required. Install it with: python3 -m pip install yfinance"
        ) from exc

    tickers = sorted(ticker_meta)
    rows: list[dict[str, Any]] = []
    total_batches = math.ceil(len(tickers) / batch_size)

    for batch_number, batch in enumerate(chunks(tickers, batch_size), start=1):
        print(
            f"Fetching price batch {batch_number}/{total_batches} ({len(batch)} tickers)",
            file=sys.stderr,
        )
        try:
            download = yf.download(
                tickers=" ".join(batch),
                period="2d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            print(f"Skipping batch {batch_number}: {exc}", file=sys.stderr)
            continue

        multi_ticker = len(batch) > 1
        for ticker in batch:
            try:
                frame = extract_frame(download, ticker, multi_ticker).dropna(how="all")
                close_series = first_existing_column(frame, ["Close", "Adj Close"]).dropna()
                if len(close_series) < 2:
                    continue
                latest_close = finite_number(close_series.iloc[-1])
                previous_close = finite_number(close_series.iloc[-2])
                if latest_close is None or previous_close in (None, 0):
                    continue

                volume_raw = None
                if "Volume" in frame:
                    volume_series = frame["Volume"].dropna()
                    if not volume_series.empty:
                        volume_raw = finite_number(volume_series.iloc[-1])

                if min_price and latest_close < min_price:
                    continue
                if min_volume and (volume_raw is None or volume_raw < min_volume):
                    continue

                change_abs = latest_close - previous_close
                change_pct = (change_abs / previous_close) * 100
                meta = ticker_meta.get(ticker, {})
                rows.append(
                    {
                        "ticker": ticker,
                        "name": meta.get("name") or ticker,
                        "price": round(latest_close, 2),
                        "previous_close": round(previous_close, 2),
                        "change_pct": round(change_pct, 2),
                        "change_abs": round(change_abs, 2),
                        "volume": format_volume(volume_raw),
                        "volume_raw": int(volume_raw) if volume_raw is not None else None,
                        "direction": "gain" if change_abs >= 0 else "loss",
                        "sector": meta.get("sector", ""),
                        "industry": meta.get("industry", ""),
                        "universe_source": meta.get("source", ""),
                        "explanation": "",
                    }
                )
            except Exception as exc:  # Keep one bad ticker from breaking the run.
                print(f"Skipping {ticker}: {exc}", file=sys.stderr)

    rows.sort(key=lambda row: abs(row["change_pct"]), reverse=True)
    return rows


def classify_tech_related(ticker: str, meta: dict[str, str]) -> tuple[bool, str]:
    if meta.get("force_tech") == "true":
        return True, "manual override"
    if ticker in TECH_TICKER_ALLOWLIST:
        return True, "known tech ticker"

    name = meta.get("name", "")
    sector = meta.get("sector", "")
    industry = meta.get("industry", "")
    search_text = f"{name} {sector} {industry}"

    if sector == "Information Technology":
        return True, "S&P Information Technology"
    if sector in {"Communication Services", "Consumer Discretionary"} and TECH_KEYWORDS.search(
        search_text
    ):
        return True, f"S&P {sector} tech-adjacent industry"
    if NON_TECH_NAME_EXCLUSIONS.search(name):
        return False, "non-tech health/biotech name"
    if TECH_KEYWORDS.search(search_text):
        return True, "technology keyword"
    return False, "not tech-related"


def fetch_yahoo_profile(ticker: str) -> dict[str, str]:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        info = yf.Ticker(ticker).get_info()
    except Exception as exc:
        print(f"Could not classify {ticker} with yfinance profile: {exc}", file=sys.stderr)
        return {}

    return {
        "name": info.get("shortName") or info.get("longName") or info.get("displayName") or "",
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
    }


def should_lookup_profile_for_cache(meta: dict[str, str]) -> bool:
    """Return whether a non-tech ticker is worth a profile lookup."""
    if meta.get("sector") or meta.get("industry"):
        return False
    name = meta.get("name", "")
    return not NON_TECH_NAME_EXCLUSIONS.search(name)


def build_tech_ticker_cache(max_profile_lookups: int) -> dict[str, Any]:
    """Download the full universe and save only tech-related tickers."""
    ticker_meta, universe_meta = load_market_universe()
    tech_tickers: dict[str, dict[str, str]] = {}
    non_tech_count = 0
    profile_lookups = 0
    total = len(ticker_meta)

    for index, (ticker, meta) in enumerate(sorted(ticker_meta.items()), start=1):
        is_tech, reason = classify_tech_related(ticker, meta)

        if (
            not is_tech
            and profile_lookups < max_profile_lookups
            and should_lookup_profile_for_cache(meta)
        ):
            profile = fetch_yahoo_profile(ticker)
            profile_lookups += 1
            if profile:
                meta.update({key: value for key, value in profile.items() if value})
                is_tech, reason = classify_tech_related(ticker, meta)

        if is_tech:
            tech_tickers[ticker] = {
                "name": meta.get("name", ticker),
                "source": meta.get("source", ""),
                "sector": meta.get("sector", ""),
                "industry": meta.get("industry", ""),
                "tech_match": reason,
            }
        else:
            non_tech_count += 1

        if index % 500 == 0:
            print(
                f"Classified {index}/{total} tickers "
                f"({len(tech_tickers)} tech, {non_tech_count} non-tech, "
                f"{profile_lookups} profile lookups)",
                file=sys.stderr,
            )

    print(
        f"Cache complete: {len(tech_tickers)} tech tickers from {total} total "
        f"({non_tech_count} non-tech, {profile_lookups} profile lookups)",
        file=sys.stderr,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe": universe_meta,
        "profile_lookups_used": profile_lookups,
        "tech_ticker_count": len(tech_tickers),
        "non_tech_count": non_tech_count,
        "tickers": tech_tickers,
    }


def write_cache(cache_data: dict[str, Any], cache_path: str) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache_data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {cache_data['tech_ticker_count']} tech tickers to {path}", file=sys.stderr)


def load_cache(
    cache_path: str,
    max_age_days: int,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]] | None:
    path = Path(cache_path)
    if not path.exists():
        print(f"No ticker cache at {path}, will download full universe", file=sys.stderr)
        return None

    try:
        cache_data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Could not read ticker cache: {exc}", file=sys.stderr)
        return None

    cache_meta: dict[str, Any] = {
        "cache_path": str(path),
        "cache_generated_at": cache_data.get("generated_at", ""),
        "cache_profile_lookups_used": cache_data.get("profile_lookups_used"),
        "cache_source_universe": cache_data.get("universe", {}),
    }
    generated_at = cache_data.get("generated_at", "")
    if generated_at:
        try:
            cache_time = datetime.fromisoformat(str(generated_at))
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - cache_time.astimezone(timezone.utc)
            cache_meta["cache_age_days"] = round(age.total_seconds() / 86400, 2)
            if age > timedelta(days=max_age_days):
                print(
                    f"Ticker cache is {age.days} days old (max {max_age_days}), "
                    f"will download full universe",
                    file=sys.stderr,
                )
                return None
            print(
                f"Using ticker cache ({cache_data.get('tech_ticker_count', '?')} tech tickers, "
                f"{cache_meta['cache_age_days']}d old)",
                file=sys.stderr,
            )
        except (TypeError, ValueError):
            print("Could not parse cache timestamp, using cache anyway", file=sys.stderr)

    tickers = cache_data.get("tickers", {})
    if not isinstance(tickers, dict) or not tickers:
        print("Ticker cache is empty, will download full universe", file=sys.stderr)
        return None

    return tickers, cache_meta


def load_universe_with_cache(
    args: argparse.Namespace,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    if not args.no_cache and not args.include_non_tech:
        cached = load_cache(args.cache_path, args.cache_max_age_days)
        if cached is not None:
            cached_tickers, cache_meta = cached
            ticker_meta = {
                ticker: make_stock_meta(
                    name=meta.get("name", ticker),
                    source=meta.get("source", "cached"),
                    sector=meta.get("sector", ""),
                    industry=meta.get("industry", ""),
                    force_tech=True,
                )
                for ticker, meta in cached_tickers.items()
            }
            universe_meta = {
                "mode": "cached_tech_tickers",
                "count": len(ticker_meta),
                **cache_meta,
            }
            return ticker_meta, universe_meta

    return load_market_universe()


def select_publishable_movers(
    ranked_rows: list[dict[str, Any]],
    ticker_meta: dict[str, dict[str, str]],
    count: int,
    tech_only: bool,
    max_sector_lookups: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    skipped_non_tech: list[str] = []
    sector_lookups = 0

    for stock in ranked_rows:
        ticker = str(stock.get("ticker", "")).upper()
        meta = ticker_meta.setdefault(ticker, make_stock_meta(stock.get("name", ticker), "price_row"))

        if not tech_only:
            is_tech = True
            reason = "tech filter disabled"
        else:
            is_tech, reason = classify_tech_related(ticker, meta)
            if not is_tech and sector_lookups < max_sector_lookups:
                profile = fetch_yahoo_profile(ticker)
                sector_lookups += 1
                if profile:
                    meta.update({key: value for key, value in profile.items() if value})
                    stock.update({key: value for key, value in profile.items() if value})
                    is_tech, reason = classify_tech_related(ticker, meta)

        if is_tech:
            stock["name"] = meta.get("name") or stock.get("name") or ticker
            stock["sector"] = meta.get("sector", stock.get("sector", ""))
            stock["industry"] = meta.get("industry", stock.get("industry", ""))
            stock["tech_match"] = reason
            selected.append(stock)
            if len(selected) >= count:
                break
        else:
            skipped_non_tech.append(ticker)

    rank_stocks(selected)
    return selected, {
        "ranked_count": len(ranked_rows),
        "tech_only": tech_only,
        "tech_selected_count": len(selected),
        "skipped_non_tech_count": len(skipped_non_tech),
        "sector_lookups": sector_lookups,
        "skipped_non_tech_sample": skipped_non_tech[:25],
    }


def rank_stocks(stocks: list[dict[str, Any]]) -> None:
    for rank, stock in enumerate(stocks, start=1):
        stock["rank"] = rank


def merge_explanations(stocks: list[dict[str, Any]], explanations: dict[str, str]) -> None:
    for stock in stocks:
        ticker = str(stock.get("ticker", "")).upper()
        stock["explanation"] = explanations.get(ticker, stock.get("explanation", "")).strip()


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    now = market_now(args.timezone)
    explanations = load_explanations(args.explanations)

    if args.input:
        payload = load_json(args.input)
        stocks = payload.get("stocks", [])
        universe_meta = payload.get("universe", {})
    else:
        ticker_override = parse_ticker_override(args.tickers)
        if ticker_override:
            ticker_meta = ticker_override
            universe_meta = {
                "mode": "manual_tickers",
                "count": len(ticker_meta),
                "sources": [],
            }
        else:
            ticker_meta, universe_meta = load_universe_with_cache(args)
        if args.list_universe:
            print(json.dumps(universe_meta, indent=2))
            raise SystemExit(0)
        ranked_rows = fetch_price_rows(
            ticker_meta=ticker_meta,
            batch_size=max(1, args.batch_size),
            min_price=max(0, args.min_price),
            min_volume=max(0, args.min_volume),
        )
        stocks, filter_meta = select_publishable_movers(
            ranked_rows=ranked_rows,
            ticker_meta=ticker_meta,
            count=args.count,
            tech_only=not args.include_non_tech,
            max_sector_lookups=max(0, args.max_sector_lookups),
        )
        universe_meta.update(filter_meta)

    merge_explanations(stocks, explanations)

    return {
        "date": args.date or now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": args.data_as_of or display_time(now),
        "source": "yfinance",
        "universe": universe_meta,
        "filters": {
            "min_price": args.min_price,
            "min_volume": args.min_volume,
            "tech_only": not args.include_non_tech,
            "max_sector_lookups": args.max_sector_lookups,
        },
        "stocks": stocks[: args.count],
    }


def main() -> int:
    args = parse_args()
    if args.refresh_cache:
        cache_data = build_tech_ticker_cache(max(0, args.max_cache_profile_lookups))
        write_cache(cache_data, args.cache_path)
        return 0

    payload = build_payload(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['stocks'])} stock movers to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
