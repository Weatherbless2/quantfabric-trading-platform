"""Read-only PostgreSQL minute-bar API used by the vn.py workbench.

The service is deliberately separate from the desktop process.  The GUI never
opens a PostgreSQL connection and therefore cannot block the market or order
event loop on a slow database query.
"""

from __future__ import annotations

import os
import json
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


def _identifier(value: str, label: str) -> str:
    """Allow only simple SQL identifiers from environment configuration."""
    if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise RuntimeError(f"{label} must be a simple SQL identifier")
    return value


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


def create_app() -> FastAPI:
    schema = _identifier(SCHEMA, "QF_HISTORY_SCHEMA")
    table = _identifier(TABLE, "QF_HISTORY_TABLE")
    app = FastAPI(title="QuantFabric HistoryDataService", version="0.1.0")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "database": "configured" if DATABASE_URL else "missing"}

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
        code = f"{exchange}:{symbol}"
        # Fetch enough one-minute rows to build the requested interval. Rows
        # are aggregated in Python so the service also works with PostgreSQL
        # versions that do not provide date_bin().
        # A bucket can straddle the query boundary. Fetch one extra interval
        # and trim after aggregation so requesting N 15-minute bars returns N
        # complete periods whenever the table has sufficient data.
        raw_limit = min(limit * interval + interval, 2000)
        query = f"""
            SELECT trdtime, open, high, low, close, vol, amt
            FROM {schema}.{table}
            WHERE market = 'S' AND stkcode = %s
            ORDER BY trdtime DESC
            LIMIT %s
        """
        try:
            with _connection() as connection:
                rows = connection.execute(query, (code, raw_limit)).fetchall()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"history database unavailable: {exc}") from exc
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
        bars = list(grouped.values())[-limit:]
        return {"symbol": symbol, "exchange": exchange, "interval": f"{interval}m", "bars": bars}

    return app
