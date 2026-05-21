#!/usr/bin/env python3
"""Generate Jekyll stock-movers data from Yahoo Finance.

The first pass fetches prices and writes ranked movers with blank explanations.
After the scheduled agent researches catalysts, run the script again with
--input and --explanations to merge AI-written explanations without refetching
prices.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "AVGO",
    "ORCL",
    "CRM",
    "AMD",
    "ADBE",
    "INTC",
    "QCOM",
    "CSCO",
    "NFLX",
    "UBER",
    "ABNB",
    "XYZ",  # Block, formerly SQ.
    "SHOP",
    "SNOW",
    "PLTR",
    "PANW",
    "CRWD",
    "ZS",
    "DDOG",
    "MDB",
    "NET",
    "TEAM",
    "NOW",
    "WDAY",
    "HUBS",
    "VEEV",
    "FTNT",
    "TTD",
    "DASH",
    "COIN",
    "MELI",
    "SE",
    "ROKU",
    "U",
    "RBLX",
    "PINS",
    "SNAP",
    "LYFT",
    "HOOD",
    "RIVN",
    "LCID",
    "ARM",
    "SMCI",
    "MRVL",
    "ON",
    "LRCX",
    "KLAC",
    "AMAT",
    "MU",
    "TXN",
    "CDNS",
    "SNPS",
    "ANSS",
    "ADI",
    "ASML",
    "NXPI",
    "INTU",
    "ADP",
    "ROP",
    "FICO",
]


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
        help="Optional comma- or space-separated ticker list. Defaults to the tech universe.",
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


def parse_tickers(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_TICKERS
    normalized = raw.replace(",", " ")
    return [ticker.strip().upper() for ticker in normalized.split() if ticker.strip()]


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


def fetch_price_rows(tickers: list[str]) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit(
            "yfinance is required. Install it with: python3 -m pip install yfinance"
        ) from exc

    download = yf.download(
        tickers=" ".join(tickers),
        period="5d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    multi_ticker = len(tickers) > 1
    rows: list[dict[str, Any]] = []

    for ticker in tickers:
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

            change_abs = latest_close - previous_close
            change_pct = (change_abs / previous_close) * 100
            rows.append(
                {
                    "ticker": ticker,
                    "name": ticker,
                    "price": round(latest_close, 2),
                    "previous_close": round(previous_close, 2),
                    "change_pct": round(change_pct, 2),
                    "change_abs": round(change_abs, 2),
                    "volume": format_volume(volume_raw),
                    "volume_raw": int(volume_raw) if volume_raw is not None else None,
                    "direction": "gain" if change_abs >= 0 else "loss",
                    "explanation": "",
                }
            )
        except Exception as exc:  # Keep one bad ticker from breaking the run.
            print(f"Skipping {ticker}: {exc}", file=sys.stderr)

    rows.sort(key=lambda row: abs(row["change_pct"]), reverse=True)
    return rows


def enrich_company_names(stocks: list[dict[str, Any]]) -> None:
    try:
        import yfinance as yf
    except ImportError:
        return

    for stock in stocks:
        ticker = stock["ticker"]
        try:
            info = yf.Ticker(ticker).get_info()
            stock["name"] = (
                info.get("shortName")
                or info.get("longName")
                or info.get("displayName")
                or ticker
            )
        except Exception:
            stock["name"] = ticker


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
    else:
        tickers = parse_tickers(args.tickers)
        stocks = fetch_price_rows(tickers)[: args.count]
        enrich_company_names(stocks)
        for rank, stock in enumerate(stocks, start=1):
            stock["rank"] = rank

    merge_explanations(stocks, explanations)

    return {
        "date": args.date or now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": args.data_as_of or display_time(now),
        "source": "yfinance",
        "stocks": stocks[: args.count],
    }


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['stocks'])} stock movers to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
