"""Read-only PostgreSQL minute-bar API used by the vn.py workbench.

The service is deliberately separate from the desktop process.  The GUI never
opens a PostgreSQL connection and therefore cannot block the market or order
event loop on a slow database query.
"""

from __future__ import annotations

import os
import json
import string
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException, Query, status
from psycopg import Connection, connect
from psycopg.rows import dict_row


EXCHANGE_NAMES = {"SSE", "SZSE"}
INTERVAL_MINUTES = {1, 5, 15}
SCHEMA = os.getenv("QF_HISTORY_SCHEMA", "tdx_init_test")
TABLE = os.getenv("QF_HISTORY_TABLE", "stkprice_1min")
DATABASE_URL = os.getenv("QF_HISTORY_DATABASE_URL", "")
AUTH_URL = os.getenv("QF_HISTORY_AUTH_URL", "http://127.0.0.1:18080")
AUTH_INTERNAL_KEY = os.getenv("QF_AUTH_INTERNAL_KEY", "")
DEFAULT_DOMAIN = os.getenv("QF_AUTH_DEFAULT_DOMAIN", "desk:cn_equity")
DEFAULT_MARKET_CODES = "SSE=S,SZSE=S"
DEFAULT_SYMBOL_TEMPLATE = "{exchange}:{symbol}"
DEFAULT_MAX_RAW_BARS = 30_100
DEFAULT_STALE_CACHE_SECONDS = 60


def _identifier(value: str, label: str) -> str:
    """Allow only simple SQL identifiers from environment configuration."""
    if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise RuntimeError(f"{label} must be a simple SQL identifier")
    return value


def _positive_int(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{label} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise RuntimeError(f"{label} must be between {minimum} and {maximum}")
    return result


def _market_codes(value: str) -> dict[str, str]:
    """Parse exchange-to-source market codes without embedding a vendor rule."""
    result: dict[str, str] = {}
    for item in value.split(","):
        exchange, separator, market_code = item.partition("=")
        exchange = exchange.strip().upper()
        market_code = market_code.strip()
        if not separator or exchange not in EXCHANGE_NAMES or len(market_code) != 1:
            raise RuntimeError("QF_HISTORY_MARKET_CODES must use SSE=<code>,SZSE=<code>")
        result[exchange] = market_code
    if set(result) != EXCHANGE_NAMES:
        raise RuntimeError("QF_HISTORY_MARKET_CODES must configure SSE and SZSE")
    return result


def _symbol_template(value: str) -> str:
    """Accept only the two safe placeholders used to build a bound SQL value."""
    try:
        fields = [field for _, field, spec, conversion in string.Formatter().parse(value)
                  if field is not None and not spec and conversion is None]
    except ValueError as exc:
        raise RuntimeError("QF_HISTORY_SYMBOL_TEMPLATE is invalid") from exc
    if not fields or any(field not in {"symbol", "exchange"} for field in fields):
        raise RuntimeError("QF_HISTORY_SYMBOL_TEMPLATE may only use {symbol} and {exchange}")
    try:
        value.format(symbol="000001", exchange="SSE")
    except (KeyError, ValueError) as exc:
        raise RuntimeError("QF_HISTORY_SYMBOL_TEMPLATE is invalid") from exc
    return value


@dataclass(frozen=True)
class HistorySource:
    """Configuration boundary between the stable API and a source-specific schema."""

    schema: str
    table: str
    market_codes: dict[str, str]
    symbol_template: str
    max_raw_bars: int
    stale_cache_seconds: int

    @classmethod
    def from_environment(cls) -> "HistorySource":
        return cls(
            schema=_identifier(os.getenv("QF_HISTORY_SCHEMA", SCHEMA), "QF_HISTORY_SCHEMA"),
            table=_identifier(os.getenv("QF_HISTORY_TABLE", TABLE), "QF_HISTORY_TABLE"),
            # These defaults preserve the existing TDX table convention. A
            # company source changes configuration or its adapter, not vn.py.
            market_codes=_market_codes(os.getenv("QF_HISTORY_MARKET_CODES", DEFAULT_MARKET_CODES)),
            symbol_template=_symbol_template(
                os.getenv("QF_HISTORY_SYMBOL_TEMPLATE", DEFAULT_SYMBOL_TEMPLATE)),
            max_raw_bars=_positive_int(os.getenv("QF_HISTORY_MAX_RAW_BARS", str(DEFAULT_MAX_RAW_BARS)),
                                       "QF_HISTORY_MAX_RAW_BARS", 1, 200_000),
            stale_cache_seconds=_positive_int(
                os.getenv("QF_HISTORY_STALE_CACHE_SECONDS", str(DEFAULT_STALE_CACHE_SECONDS)),
                "QF_HISTORY_STALE_CACHE_SECONDS", 0, 3_600),
        )

    def instrument(self, symbol: str, exchange: str) -> tuple[str, str]:
        stock_code = self.symbol_template.format(symbol=symbol, exchange=exchange)
        if len(stock_code) > 32:
            raise HTTPException(status_code=422, detail="mapped source symbol exceeds 32 characters")
        return self.market_codes[exchange], stock_code


@dataclass(frozen=True)
class CachedBars:
    created_at: float
    payload: dict[str, Any]


def _connection() -> Connection[Any]:
    if not DATABASE_URL:
        raise RuntimeError("QF_HISTORY_DATABASE_URL is not configured")
    return connect(DATABASE_URL, connect_timeout=5, row_factory=dict_row)


def _auth_session(session_id: str, symbol: str, exchange: str) -> None:
    """Ask AuthAdminService to authorize historical data access."""
    if len(session_id) != 30 or not AUTH_INTERNAL_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid history session")
    resource = f"market/{exchange}/instrument/{symbol}"
    payload = json.dumps({
        "session_id": session_id,
        "domain": DEFAULT_DOMAIN,
        "resource": resource,
        "action": "market:history",
    }).encode("utf-8")
    request = Request(
        AUTH_URL.rstrip("/") + "/v1/internal/authorize",
        data=payload,
        headers={"Content-Type": "application/json", "X-QF-Internal-Key": AUTH_INTERNAL_KEY},
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            data = response.read().decode("utf-8")
    except (HTTPError, URLError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"authorization service unavailable: {exc}") from exc
    try:
        allowed = bool(json.loads(data).get("allowed"))
    except (TypeError, ValueError):
        allowed = False
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="history permission denied")


def _number(value: Decimal | int | float | None) -> float:
    return float(value or 0)


def _aggregate_bars(rows: list[dict[str, Any]], interval: int, limit: int) -> list[dict[str, Any]]:
    """Turn source one-minute rows into the source-independent OHLCV contract."""
    grouped: dict[datetime, dict[str, Any]] = {}
    for row in reversed(rows):
        timestamp: datetime = row["trdtime"]
        bucket_minute = (timestamp.minute // interval) * interval
        bucket = timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
        current = grouped.get(bucket)
        if current is None:
            grouped[bucket] = {
                "datetime": bucket.isoformat(),
                "open": _number(row["open"]),
                "high": _number(row["high"]),
                "low": _number(row["low"]),
                "close": _number(row["close"]),
                "volume": _number(row["vol"]),
                "turnover": _number(row["amt"]),
            }
        else:
            current["high"] = max(current["high"], _number(row["high"]))
            current["low"] = min(current["low"], _number(row["low"]))
            current["close"] = _number(row["close"])
            current["volume"] += _number(row["vol"])
            current["turnover"] += _number(row["amt"])
    return list(grouped.values())[-limit:]


def create_app() -> FastAPI:
    source = HistorySource.from_environment()
    app = FastAPI(title="QuantFabric HistoryDataService", version="0.1.0")
    cache: dict[tuple[str, str, int, int], CachedBars] = {}

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "database": "configured" if DATABASE_URL else "missing",
            "source": f"{source.schema}.{source.table}",
        }

    @app.get("/v1/history/minute")
    def minute_bars(
        symbol: str = Query(min_length=1, max_length=6, pattern=r"\d{6}"),
        exchange: str = Query(min_length=3, max_length=4),
        interval: int = Query(default=1, alias="interval", ge=1, le=15),
        limit: int = Query(default=240, ge=1, le=2000),
        session_id: str = Header(alias="X-QF-Session-ID"),
    ) -> dict[str, Any]:
        exchange = exchange.upper()
        if exchange not in EXCHANGE_NAMES:
            raise HTTPException(status_code=400, detail="unsupported exchange")
        if interval not in INTERVAL_MINUTES:
            raise HTTPException(status_code=400, detail="unsupported interval")
        _auth_session(session_id, symbol, exchange)
        market_code, stock_code = source.instrument(symbol, exchange)
        # Fetch enough one-minute rows to build the requested interval. Rows
        # are aggregated in Python so source schemas can remain stable across
        # PostgreSQL versions and company market-data migrations.
        # A bucket can straddle the query boundary. Fetch one extra interval
        # and trim after aggregation so requesting N 15-minute bars returns N
        # complete periods whenever the table has sufficient data.
        raw_limit = limit * interval + interval
        if raw_limit > source.max_raw_bars:
            raise HTTPException(
                status_code=422,
                detail=(f"requested interval and limit require {raw_limit} source bars; "
                        f"QF_HISTORY_MAX_RAW_BARS is {source.max_raw_bars}"),
            )
        cache_key = (symbol, exchange, interval, limit)
        query = f"""
            SELECT trdtime, open, high, low, close, vol, amt
            FROM {source.schema}.{source.table}
            WHERE market = %s AND stkcode = %s
            ORDER BY trdtime DESC
            LIMIT %s
        """
        try:
            with _connection() as connection:
                rows = connection.execute(query, (market_code, stock_code, raw_limit)).fetchall()
        except Exception as exc:
            cached = cache.get(cache_key)
            if cached and time.monotonic() - cached.created_at <= source.stale_cache_seconds:
                # Authorization happened before reaching this branch. Serving
                # a short-lived cache lets a brief history DB outage leave the
                # chart usable without widening any trading permission.
                return {**cached.payload, "stale": True}
            raise HTTPException(status_code=503, detail=f"history database unavailable: {exc}") from exc
        payload = {
            "symbol": symbol,
            "exchange": exchange,
            "interval": f"{interval}m",
            "bars": _aggregate_bars(rows, interval, limit),
            "stale": False,
        }
        cache[cache_key] = CachedBars(created_at=time.monotonic(), payload=payload)
        return payload

    return app
