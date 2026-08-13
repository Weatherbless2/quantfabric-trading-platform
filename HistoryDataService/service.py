"""Read-only minute-bar API used by the vn.py workbench.

The service is deliberately separate from the desktop process. The GUI never
opens a ClickHouse or PostgreSQL connection and therefore cannot block the
market or order event loop on a slow historical-data query.
"""

from __future__ import annotations

import os
import json
import string
import time
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException, Query, status
from psycopg import Connection, connect
from psycopg.rows import dict_row


EXCHANGE_NAMES = {"SSE", "SZSE"}
INTERVAL_MINUTES = {1, 5, 15}
# ClickHouse is the active full-history source. PostgreSQL remains a supported
# migration fallback for teams that already deployed the former service.
DEFAULT_BACKEND = "clickhouse"
DEFAULT_CLICKHOUSE_URL = "http://172.16.20.10:8123"
DEFAULT_CLICKHOUSE_DATABASE = "tdxdata"
DEFAULT_TABLE = "stkprice_1min"
DEFAULT_POSTGRES_SCHEMA = "tdx_init_test"
SCHEMA = os.getenv("QF_HISTORY_SCHEMA", DEFAULT_POSTGRES_SCHEMA)
TABLE = os.getenv("QF_HISTORY_TABLE", DEFAULT_TABLE)
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


def _history_backend(value: str) -> str:
    """Restrict the source choice to supported, explicitly named adapters."""
    backend = value.strip().lower()
    if backend not in {"clickhouse", "postgres"}:
        raise RuntimeError("QF_HISTORY_BACKEND must be clickhouse or postgres")
    return backend


def _clickhouse_url(value: str) -> str:
    """Validate the endpoint and keep credentials out of URLs and diagnostics."""
    parsed = urlparse(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise RuntimeError("QF_HISTORY_CLICKHOUSE_URL must be an http(s) endpoint without credentials")
    return value.rstrip("/")


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

    backend: str
    schema: str
    table: str
    clickhouse_url: str
    clickhouse_database: str
    clickhouse_username: str
    clickhouse_password: str
    market_codes: dict[str, str]
    symbol_template: str
    max_raw_bars: int
    stale_cache_seconds: int

    @classmethod
    def from_environment(cls) -> "HistorySource":
        return cls(
            backend=_history_backend(os.getenv("QF_HISTORY_BACKEND", DEFAULT_BACKEND)),
            schema=_identifier(os.getenv("QF_HISTORY_SCHEMA", SCHEMA), "QF_HISTORY_SCHEMA"),
            table=_identifier(os.getenv("QF_HISTORY_TABLE", TABLE), "QF_HISTORY_TABLE"),
            clickhouse_url=_clickhouse_url(
                os.getenv("QF_HISTORY_CLICKHOUSE_URL", DEFAULT_CLICKHOUSE_URL)),
            clickhouse_database=_identifier(
                os.getenv("QF_HISTORY_CLICKHOUSE_DATABASE", DEFAULT_CLICKHOUSE_DATABASE),
                "QF_HISTORY_CLICKHOUSE_DATABASE"),
            clickhouse_username=os.getenv("QF_HISTORY_CLICKHOUSE_USERNAME", ""),
            clickhouse_password=os.getenv("QF_HISTORY_CLICKHOUSE_PASSWORD", ""),
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


def _clickhouse_query(source: HistorySource, query: str,
                      parameters: dict[str, str | int]) -> str:
    """Run a parameterized ClickHouse HTTP query and return its response body.

    ClickHouse expands ``{name:Type}`` placeholders from ``param_name`` HTTP
    parameters. This keeps exchange, symbol and limit out of SQL text while
    the connection password stays in the Authorization header.
    """
    if not source.clickhouse_username or not source.clickhouse_password:
        raise RuntimeError("ClickHouse credentials are not configured")
    encoded = urlencode({f"param_{key}": value for key, value in parameters.items()})
    token = b64encode(
        f"{source.clickhouse_username}:{source.clickhouse_password}".encode("utf-8")).decode("ascii")
    request = Request(
        f"{source.clickhouse_url}/?{encoded}",
        data=query.encode("utf-8"),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, OSError) as exc:
        # Do not include server diagnostics here: a proxy may echo headers or
        # endpoint details. The operator has the service-side logs instead.
        raise RuntimeError("ClickHouse query failed") from exc


def _clickhouse_rows(source: HistorySource, market_code: str, stock_code: str,
                     raw_limit: int) -> list[dict[str, Any]]:
    query = f"""
        SELECT trdtime, open, high, low, close, vol, amt
        FROM {source.clickhouse_database}.{source.table}
        WHERE market = {{market:String}} AND stkcode = {{stock_code:String}}
        ORDER BY trdtime DESC
        LIMIT {{limit:UInt32}}
        FORMAT JSONEachRow
    """
    body = _clickhouse_query(source, query, {
        "market": market_code,
        "stock_code": stock_code,
        "limit": raw_limit,
    })
    rows: list[dict[str, Any]] = []
    try:
        for line in body.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            timestamp = row["trdtime"]
            if isinstance(timestamp, str):
                row["trdtime"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif not isinstance(timestamp, datetime):
                raise TypeError("trdtime is not a date-time value")
            rows.append(row)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ClickHouse returned invalid minute-bar data") from exc
    return rows


def _postgres_rows(source: HistorySource, market_code: str, stock_code: str,
                   raw_limit: int) -> list[dict[str, Any]]:
    query = f"""
        SELECT trdtime, open, high, low, close, vol, amt
        FROM {source.schema}.{source.table}
        WHERE market = %s AND stkcode = %s
        ORDER BY trdtime DESC
        LIMIT %s
    """
    with _connection() as connection:
        return connection.execute(query, (market_code, stock_code, raw_limit)).fetchall()


def _fetch_rows(source: HistorySource, market_code: str, stock_code: str,
                raw_limit: int) -> list[dict[str, Any]]:
    """Route to one source adapter without changing the public OHLCV contract."""
    if source.backend == "clickhouse":
        return _clickhouse_rows(source, market_code, stock_code, raw_limit)
    return _postgres_rows(source, market_code, stock_code, raw_limit)


def _source_ready(source: HistorySource) -> None:
    if source.backend == "clickhouse":
        _clickhouse_query(source, "SELECT 1 FORMAT JSONEachRow", {})
        return
    with _connection() as connection:
        connection.execute("SELECT 1").fetchone()


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


def _number(value: Decimal | int | float | str | None) -> float:
    """Normalize database numeric representations for a JSON-safe response."""
    if value is None:
        return 0.0
    return float(value)


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
        configured = (
            bool(source.clickhouse_username and source.clickhouse_password)
            if source.backend == "clickhouse" else bool(DATABASE_URL)
        )
        return {
            "status": "ok",
            "backend": source.backend,
            "database": "configured" if configured else "missing",
            "source": (f"{source.clickhouse_database}.{source.table}"
                       if source.backend == "clickhouse" else f"{source.schema}.{source.table}"),
        }

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        try:
            _source_ready(source)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="history data source unavailable") from exc
        return {"status": "ready", "backend": source.backend}

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
        try:
            rows = _fetch_rows(source, market_code, stock_code, raw_limit)
        except Exception as exc:
            cached = cache.get(cache_key)
            if cached and time.monotonic() - cached.created_at <= source.stale_cache_seconds:
                # Authorization happened before reaching this branch. Serving
                # a short-lived cache lets a brief history DB outage leave the
                # chart usable without widening any trading permission.
                return {**cached.payload, "stale": True}
            raise HTTPException(status_code=503, detail="history data source unavailable") from exc
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
