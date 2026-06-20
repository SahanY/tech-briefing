#!/usr/bin/env python3
"""Generate Jekyll stock-movers data from the Alpaca Market Data API.

Uses the Alpaca Market Data API to fetch snapshots for a curated list of
~200 tech tickers.  The ticker list is
stored in a JSON cache that should be refreshed weekly (--refresh-cache).

Usage:
  Daily run:   python generate_stock_movers.py --output _data/stock_movers.json
  Weekly:      python generate_stock_movers.py --refresh-cache
  Merge explanations:
               python generate_stock_movers.py --input existing.json --explanations expl.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Curated tech ticker universe (~200 Nasdaq + S&P tech/software companies)
# ---------------------------------------------------------------------------
# Refreshed weekly via --refresh-cache (which re-validates against Alpaca).
# This list is the fallback if no cache exists.

TECH_TICKERS: list[dict[str, str]] = [
    # Mega-cap tech
    {"ticker": "AAPL", "name": "Apple Inc."},
    {"ticker": "MSFT", "name": "Microsoft Corporation"},
    {"ticker": "GOOGL", "name": "Alphabet Inc."},
    {"ticker": "AMZN", "name": "Amazon.com Inc."},
    {"ticker": "META", "name": "Meta Platforms Inc."},
    {"ticker": "NVDA", "name": "NVIDIA Corporation"},
    {"ticker": "TSLA", "name": "Tesla Inc."},
    {"ticker": "AVGO", "name": "Broadcom Inc."},
    {"ticker": "ORCL", "name": "Oracle Corporation"},
    {"ticker": "CRM", "name": "Salesforce Inc."},
    # Semiconductors
    {"ticker": "AMD", "name": "Advanced Micro Devices"},
    {"ticker": "INTC", "name": "Intel Corporation"},
    {"ticker": "QCOM", "name": "Qualcomm Inc."},
    {"ticker": "TXN", "name": "Texas Instruments"},
    {"ticker": "MU", "name": "Micron Technology"},
    {"ticker": "AMAT", "name": "Applied Materials"},
    {"ticker": "LRCX", "name": "Lam Research"},
    {"ticker": "KLAC", "name": "KLA Corporation"},
    {"ticker": "ADI", "name": "Analog Devices"},
    {"ticker": "NXPI", "name": "NXP Semiconductors"},
    {"ticker": "MRVL", "name": "Marvell Technology"},
    {"ticker": "ON", "name": "ON Semiconductor"},
    {"ticker": "ASML", "name": "ASML Holding"},
    {"ticker": "ARM", "name": "Arm Holdings"},
    {"ticker": "SNPS", "name": "Synopsys Inc."},
    {"ticker": "CDNS", "name": "Cadence Design Systems"},
    {"ticker": "SMCI", "name": "Super Micro Computer"},
    {"ticker": "MCHP", "name": "Microchip Technology"},
    {"ticker": "SWKS", "name": "Skyworks Solutions"},
    {"ticker": "MPWR", "name": "Monolithic Power Systems"},
    {"ticker": "WOLF", "name": "Wolfspeed Inc."},
    {"ticker": "GFS", "name": "GlobalFoundries"},
    {"ticker": "TSM", "name": "Taiwan Semiconductor"},
    # Enterprise software & SaaS
    {"ticker": "NOW", "name": "ServiceNow Inc."},
    {"ticker": "ADBE", "name": "Adobe Inc."},
    {"ticker": "INTU", "name": "Intuit Inc."},
    {"ticker": "WDAY", "name": "Workday Inc."},
    {"ticker": "SNOW", "name": "Snowflake Inc."},
    {"ticker": "DDOG", "name": "Datadog Inc."},
    {"ticker": "MDB", "name": "MongoDB Inc."},
    {"ticker": "HUBS", "name": "HubSpot Inc."},
    {"ticker": "TEAM", "name": "Atlassian Corporation"},
    {"ticker": "VEEV", "name": "Veeva Systems"},
    {"ticker": "ZS", "name": "Zscaler Inc."},
    {"ticker": "ANSS", "name": "ANSYS Inc."},
    {"ticker": "FICO", "name": "Fair Isaac Corporation"},
    {"ticker": "SPLK", "name": "Splunk Inc."},
    {"ticker": "BILL", "name": "BILL Holdings"},
    {"ticker": "CFLT", "name": "Confluent Inc."},
    {"ticker": "ESTC", "name": "Elastic N.V."},
    {"ticker": "GTLB", "name": "GitLab Inc."},
    {"ticker": "MNDY", "name": "monday.com Ltd."},
    {"ticker": "S", "name": "SentinelOne Inc."},
    {"ticker": "DOCN", "name": "DigitalOcean Holdings"},
    {"ticker": "BRZE", "name": "Braze Inc."},
    {"ticker": "PCOR", "name": "Procore Technologies"},
    {"ticker": "DT", "name": "Dynatrace Inc."},
    {"ticker": "SMAR", "name": "Smartsheet Inc."},
    {"ticker": "PD", "name": "PagerDuty Inc."},
    {"ticker": "ALRM", "name": "Alarm.com Holdings"},
    {"ticker": "ASAN", "name": "Asana Inc."},
    {"ticker": "FRSH", "name": "Freshworks Inc."},
    {"ticker": "ZI", "name": "ZoomInfo Technologies"},
    {"ticker": "JAMF", "name": "Jamf Holding"},
    {"ticker": "TOST", "name": "Toast Inc."},
    {"ticker": "IOT", "name": "Samsara Inc."},
    {"ticker": "FOUR", "name": "Shift4 Payments"},
    {"ticker": "PAYC", "name": "Paycom Software"},
    {"ticker": "PCTY", "name": "Paylocity Holding"},
    {"ticker": "VERX", "name": "Vertex Inc."},
    # Cybersecurity
    {"ticker": "CRWD", "name": "CrowdStrike Holdings"},
    {"ticker": "PANW", "name": "Palo Alto Networks"},
    {"ticker": "FTNT", "name": "Fortinet Inc."},
    {"ticker": "NET", "name": "Cloudflare Inc."},
    {"ticker": "OKTA", "name": "Okta Inc."},
    {"ticker": "CYBR", "name": "CyberArk Software"},
    {"ticker": "RPD", "name": "Rapid7 Inc."},
    {"ticker": "TENB", "name": "Tenable Holdings"},
    {"ticker": "VRNS", "name": "Varonis Systems"},
    # Networking & infrastructure
    {"ticker": "CSCO", "name": "Cisco Systems"},
    {"ticker": "ANET", "name": "Arista Networks"},
    {"ticker": "AKAM", "name": "Akamai Technologies"},
    {"ticker": "FFIV", "name": "F5 Inc."},
    {"ticker": "NTAP", "name": "NetApp Inc."},
    {"ticker": "PSTG", "name": "Pure Storage"},
    {"ticker": "HPE", "name": "Hewlett Packard Enterprise"},
    {"ticker": "HPQ", "name": "HP Inc."},
    {"ticker": "DELL", "name": "Dell Technologies"},
    # Consumer internet & platforms
    {"ticker": "NFLX", "name": "Netflix Inc."},
    {"ticker": "ABNB", "name": "Airbnb Inc."},
    {"ticker": "UBER", "name": "Uber Technologies"},
    {"ticker": "LYFT", "name": "Lyft Inc."},
    {"ticker": "DASH", "name": "DoorDash Inc."},
    {"ticker": "SNAP", "name": "Snap Inc."},
    {"ticker": "PINS", "name": "Pinterest Inc."},
    {"ticker": "RBLX", "name": "Roblox Corporation"},
    {"ticker": "ROKU", "name": "Roku Inc."},
    {"ticker": "TTD", "name": "The Trade Desk"},
    {"ticker": "SPOT", "name": "Spotify Technology"},
    {"ticker": "SHOP", "name": "Shopify Inc."},
    {"ticker": "SE", "name": "Sea Limited"},
    {"ticker": "MELI", "name": "MercadoLibre Inc."},
    {"ticker": "BKNG", "name": "Booking Holdings"},
    {"ticker": "EBAY", "name": "eBay Inc."},
    {"ticker": "ETSY", "name": "Etsy Inc."},
    {"ticker": "ZM", "name": "Zoom Video Communications"},
    {"ticker": "MTCH", "name": "Match Group"},
    {"ticker": "DUOL", "name": "Duolingo Inc."},
    {"ticker": "RDDT", "name": "Reddit Inc."},
    {"ticker": "GRAB", "name": "Grab Holdings"},
    # AI & data
    {"ticker": "PLTR", "name": "Palantir Technologies"},
    {"ticker": "AI", "name": "C3.ai Inc."},
    {"ticker": "PATH", "name": "UiPath Inc."},
    {"ticker": "BBAI", "name": "BigBear.ai Holdings"},
    {"ticker": "SOUN", "name": "SoundHound AI"},
    {"ticker": "UPST", "name": "Upstart Holdings"},
    {"ticker": "BFLY", "name": "Butterfly Network"},
    # Fintech & payments
    {"ticker": "SQ", "name": "Block Inc."},
    {"ticker": "PYPL", "name": "PayPal Holdings"},
    {"ticker": "COIN", "name": "Coinbase Global"},
    {"ticker": "HOOD", "name": "Robinhood Markets"},
    {"ticker": "AFRM", "name": "Affirm Holdings"},
    {"ticker": "SOFI", "name": "SoFi Technologies"},
    {"ticker": "MSTR", "name": "MicroStrategy Inc."},
    {"ticker": "XYZ", "name": "Block Inc. (XYZ)"},
    {"ticker": "FI", "name": "Fiserv Inc."},
    {"ticker": "GPN", "name": "Global Payments"},
    {"ticker": "FIS", "name": "Fidelity National Information Services"},
    {"ticker": "INFY", "name": "Infosys Limited"},
    {"ticker": "WIT", "name": "Wipro Limited"},
    # EV & autonomous
    {"ticker": "RIVN", "name": "Rivian Automotive"},
    {"ticker": "LCID", "name": "Lucid Group"},
    {"ticker": "NIO", "name": "NIO Inc."},
    {"ticker": "XPEV", "name": "XPeng Inc."},
    {"ticker": "LI", "name": "Li Auto Inc."},
    # Gaming
    {"ticker": "U", "name": "Unity Software"},
    {"ticker": "EA", "name": "Electronic Arts"},
    {"ticker": "TTWO", "name": "Take-Two Interactive"},
    {"ticker": "RBLX", "name": "Roblox Corporation"},
    # Hardware & devices
    {"ticker": "ZBRA", "name": "Zebra Technologies"},
    {"ticker": "TER", "name": "Teradyne Inc."},
    {"ticker": "KEYS", "name": "Keysight Technologies"},
    {"ticker": "GLW", "name": "Corning Inc."},
    {"ticker": "STX", "name": "Seagate Technology"},
    {"ticker": "WDC", "name": "Western Digital"},
    # IT consulting & services
    {"ticker": "ACN", "name": "Accenture plc"},
    {"ticker": "IBM", "name": "IBM Corporation"},
    {"ticker": "CTSH", "name": "Cognizant Technology Solutions"},
    {"ticker": "EPAM", "name": "EPAM Systems"},
    {"ticker": "GDDY", "name": "GoDaddy Inc."},
    {"ticker": "GEN", "name": "Gen Digital Inc."},
    {"ticker": "LDOS", "name": "Leidos Holdings"},
    # Telecom tech
    {"ticker": "TMUS", "name": "T-Mobile US"},
    {"ticker": "VZ", "name": "Verizon Communications"},
    {"ticker": "T", "name": "AT&T Inc."},
    # Ad tech & martech
    {"ticker": "APP", "name": "AppLovin Corporation"},
    {"ticker": "IS", "name": "IronSource / Unity"},
    {"ticker": "MGNI", "name": "Magnite Inc."},
    {"ticker": "PUBM", "name": "PubMatic Inc."},
    {"ticker": "DV", "name": "DoubleVerify Holdings"},
    {"ticker": "IAS", "name": "Integral Ad Science"},
    # Other notable tech
    {"ticker": "CELH", "name": "Celsius Holdings"},
    {"ticker": "DKNG", "name": "DraftKings Inc."},
    {"ticker": "CRSP", "name": "CRISPR Therapeutics"},
    {"ticker": "IONQ", "name": "IonQ Inc."},
    {"ticker": "RGTI", "name": "Rigetti Computing"},
    {"ticker": "QUBT", "name": "Quantum Computing Inc."},
    {"ticker": "LUNR", "name": "Intuitive Machines"},
    {"ticker": "RKLB", "name": "Rocket Lab USA"},
    {"ticker": "ASTS", "name": "AST SpaceMobile"},
    {"ticker": "VRT", "name": "Vertiv Holdings"},
    {"ticker": "PWR", "name": "Quanta Services"},
    {"ticker": "APH", "name": "Amphenol Corporation"},
    {"ticker": "IT", "name": "Gartner Inc."},
    {"ticker": "FLEX", "name": "Flex Ltd."},
    {"ticker": "JNPR", "name": "Juniper Networks"},
    {"ticker": "CIEN", "name": "Ciena Corporation"},
    {"ticker": "LITE", "name": "Lumentum Holdings"},
    {"ticker": "CRUS", "name": "Cirrus Logic"},
    {"ticker": "ONTO", "name": "Onto Innovation"},
    {"ticker": "AMKR", "name": "Amkor Technology"},
    {"ticker": "COHR", "name": "Coherent Corp."},
    {"ticker": "LSCC", "name": "Lattice Semiconductor"},
]

# De-duplicate by ticker
_seen: set[str] = set()
_deduped: list[dict[str, str]] = []
for _t in TECH_TICKERS:
    if _t["ticker"] not in _seen:
        _seen.add(_t["ticker"])
        _deduped.append(_t)
TECH_TICKERS = _deduped
del _seen, _deduped

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
USER_AGENT = "TechBriefingMarketMovers/2.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="_data/stock_movers.json",
                        help="Path for the Jekyll JSON data file.")
    parser.add_argument("--input",
                        help="Existing stock_movers JSON to reuse (skip price fetch).")
    parser.add_argument("--explanations",
                        help="JSON file with ticker-to-explanation mapping.")
    parser.add_argument("--count", type=int, default=15,
                        help="Number of movers to publish.")
    parser.add_argument("--date",
                        help="Trading date to write into the JSON payload.")
    parser.add_argument("--data-as-of",
                        help='Display timestamp, e.g. "2026-06-13, 9:00 AM CT".')
    parser.add_argument("--timezone", default="America/Chicago",
                        help="Timezone for generated_at and display timestamps.")
    parser.add_argument("--cache-path", default="_data/tech_ticker_cache.json",
                        help="Path for the validated tech ticker cache.")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Validate tickers against Alpaca and write cache. No price fetch.")
    parser.add_argument("--cache-max-age-days", type=int, default=7,
                        help="Maximum age before the ticker cache is stale.")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignore the ticker cache; use the built-in list directly.")
    parser.add_argument("--alpaca-key-id",
                        default=os.environ.get("APCA_API_KEY_ID", ""),
                        help="Alpaca API key ID (or set APCA_API_KEY_ID env var).")
    parser.add_argument("--alpaca-secret-key",
                        default=os.environ.get("APCA_API_SECRET_KEY", ""),
                        help="Alpaca API secret key (or set APCA_API_SECRET_KEY env var).")
    return parser.parse_args()


def market_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def display_time(now: datetime) -> str:
    time_text = now.strftime("%I:%M %p").lstrip("0")
    return f"{now.date().isoformat()}, {time_text} CT"


def finite(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def format_volume(v: Any) -> str:
    n = finite(v)
    if n is None:
        return ""
    a = abs(n)
    if a >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def alpaca_request(
    url: str,
    key_id: str,
    secret_key: str,
) -> dict[str, Any]:
    """Make an authenticated GET request to Alpaca and return parsed JSON."""
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Snapshot fetching
# ---------------------------------------------------------------------------

def fetch_snapshots(
    tickers: list[str],
    key_id: str,
    secret_key: str,
    batch_size: int = 200,
) -> dict[str, Any]:
    """Fetch Alpaca snapshots for all tickers, batching if needed."""
    all_snapshots: dict[str, Any] = {}
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        symbols = ",".join(batch)
        url = f"{ALPACA_DATA_BASE}/stocks/snapshots?symbols={symbols}&feed=iex"
        print(
            f"Fetching Alpaca snapshots batch {i // batch_size + 1} "
            f"({len(batch)} tickers)",
            file=sys.stderr,
        )
        try:
            data = alpaca_request(url, key_id, secret_key)
            all_snapshots.update(data)
        except Exception as exc:
            print(f"Snapshot batch error: {exc}", file=sys.stderr)
    return all_snapshots


def snapshots_to_rows(
    snapshots: dict[str, Any],
    ticker_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert Alpaca snapshot data into ranked mover rows."""
    rows: list[dict[str, Any]] = []
    for ticker, snap in snapshots.items():
        try:
            daily = snap.get("dailyBar") or {}
            prev = snap.get("prevDailyBar") or {}
            latest_trade = snap.get("latestTrade") or {}

            price = finite(daily.get("c") or latest_trade.get("p"))
            prev_close = finite(prev.get("c"))
            volume_raw = finite(daily.get("v"))

            if price is None or prev_close is None or prev_close == 0:
                continue

            change_abs = price - prev_close
            change_pct = (change_abs / prev_close) * 100

            rows.append({
                "ticker": ticker,
                "name": ticker_names.get(ticker, ticker),
                "price": round(price, 2),
                "previous_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "change_abs": round(change_abs, 2),
                "volume": format_volume(volume_raw),
                "volume_raw": int(volume_raw) if volume_raw is not None else None,
                "direction": "gain" if change_abs >= 0 else "loss",
                "explanation": "",
            })
        except Exception as exc:
            print(f"Skipping {ticker}: {exc}", file=sys.stderr)

    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Ticker cache
# ---------------------------------------------------------------------------

def validate_tickers_against_alpaca(
    tickers: list[str],
    key_id: str,
    secret_key: str,
) -> list[str]:
    """Return only tickers that Alpaca returns valid snapshot data for."""
    snapshots = fetch_snapshots(tickers, key_id, secret_key)
    valid = [t for t in tickers if t in snapshots]
    invalid = [t for t in tickers if t not in snapshots]
    if invalid:
        print(f"Removed {len(invalid)} invalid tickers: {invalid[:20]}...", file=sys.stderr)
    print(f"Validated {len(valid)} tickers with Alpaca", file=sys.stderr)
    return valid


def build_cache(key_id: str, secret_key: str) -> dict[str, Any]:
    """Validate the built-in ticker list against Alpaca and build cache."""
    all_tickers = [t["ticker"] for t in TECH_TICKERS]
    valid = validate_tickers_against_alpaca(all_tickers, key_id, secret_key)
    name_map = {t["ticker"]: t["name"] for t in TECH_TICKERS}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "alpaca_validated",
        "total_candidates": len(all_tickers),
        "valid_count": len(valid),
        "tickers": [
            {"ticker": t, "name": name_map.get(t, t)} for t in valid
        ],
    }


def write_cache(cache_data: dict[str, Any], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache_data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {cache_data['valid_count']} tickers to {p}", file=sys.stderr)


def load_cache(path: str, max_age_days: int) -> list[dict[str, str]] | None:
    p = Path(path)
    if not p.exists():
        print(f"No cache at {p}, using built-in list", file=sys.stderr)
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Cache read error: {exc}", file=sys.stderr)
        return None

    ts = data.get("generated_at", "")
    if ts:
        try:
            cache_time = datetime.fromisoformat(str(ts))
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - cache_time.astimezone(timezone.utc)
            if age > timedelta(days=max_age_days):
                print(f"Cache is {age.days}d old (max {max_age_days}), using built-in list", file=sys.stderr)
                return None
            print(f"Using ticker cache ({data.get('valid_count', '?')} tickers, {age.days}d old)", file=sys.stderr)
        except (TypeError, ValueError):
            pass

    tickers = data.get("tickers", [])
    if not tickers:
        return None
    return tickers


def get_ticker_list(args: argparse.Namespace) -> list[dict[str, str]]:
    """Load tickers from cache or fall back to built-in list."""
    if not args.no_cache:
        cached = load_cache(args.cache_path, args.cache_max_age_days)
        if cached:
            return cached
    return TECH_TICKERS


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------

def load_explanations(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict) and "stocks" in data:
        return {
            str(r.get("ticker", "")).upper(): str(r.get("explanation", "")).strip()
            for r in data["stocks"] if r.get("ticker") and r.get("explanation")
        }
    return {
        str(k).upper(): str(v).strip() for k, v in data.items() if v
    }


def sanitize_for_yaml(text: str) -> str:
    """Make a string safe for Jekyll's YAML parser (Psych/safe_yaml).

    Jekyll v3 reads ``_data/*.json`` through a YAML parser, so JSON
    string values must not contain characters that break YAML scanning.
    Bare single-quotes (apostrophes) inside flow scalars cause
    ``found unexpected end of stream while scanning a quoted scalar``.
    Replace them with the Unicode right-single-quotation-mark (U+2019),
    which renders identically in browsers but is not a YAML control
    character.
    """
    text = text.replace("'", "’")   # ' -> ’ (right single quote)
    return text


def sanitize_payload(obj: Any) -> Any:
    """Recursively sanitize all string values in a JSON-serialisable object."""
    if isinstance(obj, str):
        return sanitize_for_yaml(obj)
    if isinstance(obj, dict):
        return {k: sanitize_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_payload(v) for v in obj]
    return obj


def merge_explanations(stocks: list[dict[str, Any]], explanations: dict[str, str]) -> None:
    for s in stocks:
        ticker = str(s.get("ticker", "")).upper()
        s["explanation"] = explanations.get(ticker, s.get("explanation", "")).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    now = market_now(args.timezone)
    explanations = load_explanations(args.explanations)

    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        stocks = payload.get("stocks", [])
    else:
        ticker_list = get_ticker_list(args)
        tickers = [t["ticker"] for t in ticker_list]
        name_map = {t["ticker"]: t["name"] for t in ticker_list}

        snapshots = fetch_snapshots(tickers, args.alpaca_key_id, args.alpaca_secret_key)
        rows = snapshots_to_rows(snapshots, name_map)
        stocks = rows[: args.count]

        # Assign ranks
        for rank, s in enumerate(stocks, start=1):
            s["rank"] = rank

    merge_explanations(stocks, explanations)

    return {
        "date": args.date or now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": args.data_as_of or display_time(now),
        "source": "alpaca",
        "universe": {
            "mode": "curated_tech_200",
            "tech_only": True,
            "count": len(get_ticker_list(args)),
        },
        "filters": {
            "tech_only": True,
        },
        "stocks": stocks[: args.count],
    }


def main() -> int:
    args = parse_args()

    if not args.alpaca_key_id or not args.alpaca_secret_key:
        # Try loading from .alpaca-config
        config_path = Path(__file__).resolve().parent.parent / ".alpaca-config"
        if config_path.exists():
            for line in config_path.read_text().strip().splitlines():
                line = line.strip()
                if line.startswith("APCA_API_KEY_ID="):
                    args.alpaca_key_id = args.alpaca_key_id or line.split("=", 1)[1].strip()
                elif line.startswith("APCA_