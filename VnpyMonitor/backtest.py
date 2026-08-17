"""Asynchronous HTTP client for the local read-only backtest service."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vnpy.trader.ui import QtCore


@dataclass(frozen=True)
class BacktestParameters:
    symbol: str
    exchange: str
    start: str
    end: str
    interval: int
    fast_window: int
    slow_window: int
    capital: float
    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.001
    slippage_bps: float = 2.0


class BacktestLoader(QtCore.QObject):
    """Run one remote backtest without blocking the desktop event loop."""

    loaded = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, service_url: str, session_id: str,
                 parameters: BacktestParameters) -> None:
        super().__init__()
        self.service_url = service_url.rstrip("/")
        self.session_id = session_id
        self.parameters = parameters

    @QtCore.Slot()
    def run(self) -> None:
        try:
            request = Request(
                f"{self.service_url}/v1/backtests",
                data=json.dumps(asdict(self.parameters)).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-QF-Session-ID": self.session_id,
                },
                method="POST",
            )
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid backtest response")
            self.loaded.emit(payload)
        except HTTPError as exc:
            self.failed.emit(f"回测服务拒绝请求（HTTP {exc.code}）")
        except (URLError, OSError, ValueError) as exc:
            self.failed.emit(f"回测服务不可用：{exc}")


def start_backtest_load(service_url: str, session_id: str,
                        parameters: BacktestParameters,
                        on_loaded=None, on_failed=None):
    """Create a worker after consumers have connected to its signals."""
    thread = QtCore.QThread()
    worker = BacktestLoader(service_url, session_id, parameters)
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
