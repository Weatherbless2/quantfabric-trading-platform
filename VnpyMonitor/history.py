"""Asynchronous client for the read-only historical market data service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vnpy.trader.ui import QtCore


@dataclass(frozen=True)
class HistoryBar:
    """Transport-neutral OHLCV bar returned by HistoryDataService."""

    datetime: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float


class HistoryLoader(QtCore.QObject):
    """Fetch one symbol without blocking the Qt event loop."""

    loaded = QtCore.Signal(str, int, list)
    failed = QtCore.Signal(str, str)

    def __init__(self, service_url: str, session_id: str, vt_symbol: str,
                 interval: int = 1, limit: int = 240) -> None:
        super().__init__()
        self.service_url = service_url.rstrip("/")
        self.session_id = session_id
        self.vt_symbol = vt_symbol
        self.interval = interval
        self.limit = limit

    @QtCore.Slot()
    def run(self) -> None:
        try:
            symbol, exchange = self.vt_symbol.rsplit(".", 1)
            query = urlencode({"symbol": symbol, "exchange": exchange,
                               "interval": self.interval, "limit": self.limit})
            request = Request(
                f"{self.service_url}/v1/history/minute?{query}",
                headers={"X-QF-Session-ID": self.session_id},
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            bars = [self._parse_bar(item) for item in payload.get("bars", [])]
            self.loaded.emit(self.vt_symbol, self.interval, bars)
        except (HTTPError, URLError, OSError, ValueError, KeyError, TypeError) as exc:
            self.failed.emit(self.vt_symbol, str(exc))

    @staticmethod
    def _parse_bar(item: dict) -> HistoryBar:
        timestamp = datetime.fromisoformat(str(item["datetime"]))
        # Realtime ticks use local naive datetimes; normalize DB timezone
        # values before merging the two sources.
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone().replace(tzinfo=None)
        return HistoryBar(
            datetime=timestamp,
            open_price=float(item["open"]),
            high_price=float(item["high"]),
            low_price=float(item["low"]),
            close_price=float(item["close"]),
            volume=float(item.get("volume", 0) or 0),
            turnover=float(item.get("turnover", 0) or 0),
        )


def start_history_load(service_url: str, session_id: str, vt_symbol: str,
                       interval: int = 1, limit: int = 240,
                       on_loaded=None, on_failed=None):
    """Create a loader after all consumers are connected to its signals."""
    thread = QtCore.QThread()
    worker = HistoryLoader(service_url, session_id, vt_symbol, interval, limit)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.loaded.connect(thread.quit)
    worker.failed.connect(thread.quit)
    if on_loaded:
        worker.loaded.connect(on_loaded)
    if on_failed:
        worker.failed.connect(on_failed)
    worker.loaded.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker
