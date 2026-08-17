import json
import unittest
from unittest.mock import patch

from VnpyMonitor.backtest import BacktestLoader, BacktestParameters


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def read(self) -> bytes:
        return self.payload


class BacktestLoaderTest(unittest.TestCase):
    def test_request_uses_session_and_returns_payload(self) -> None:
        parameters = BacktestParameters(
            symbol="300007", exchange="SZSE", start="2026-01-01", end="2026-01-31",
            interval=5, fast_window=10, slow_window=30, capital=1_000_000,
        )
        loaded = []
        loader = BacktestLoader("http://127.0.0.1:18082/", "a" * 30, parameters)
        loader.loaded.connect(loaded.append)
        with patch("VnpyMonitor.backtest.urlopen", return_value=FakeHttpResponse({"bars": 42})) as open_request:
            loader.run()
        request = open_request.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18082/v1/backtests")
        self.assertEqual(request.get_header("X-qf-session-id"), "a" * 30)
        self.assertEqual(json.loads(request.data)["symbol"], "300007")
        self.assertEqual(loaded, [{"bars": 42}])


if __name__ == "__main__":
    unittest.main()
