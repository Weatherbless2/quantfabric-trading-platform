import unittest
from datetime import date, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from BacktestService.engine import BacktestResult
from BacktestService.service import create_app
from HistoryDataService.service import HistorySource


def _source() -> HistorySource:
    return HistorySource(
        backend="clickhouse", schema="tdx", table="bars",
        clickhouse_url="http://unused", clickhouse_database="tdxdata",
        clickhouse_username="readonly", clickhouse_password="secret",
        market_codes={"SSE": "S", "SZSE": "S"}, symbol_template="{exchange}:{symbol}",
        max_raw_bars=100_000, stale_cache_seconds=0,
    )


class BacktestServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(_source()))

    def test_backtest_authorizes_then_returns_report(self) -> None:
        result = BacktestResult(
            config={"symbol": "300007", "start": "2026-01-01T00:00:00"},
            source="tdxdata.bars", bars=42, final_equity=1_010_000,
            pnl=10_000, return_rate=0.01,
        )
        with patch("BacktestService.service._auth_session") as authorize, \
                patch("BacktestService.service.run_backtest", return_value=result) as run:
            response = self.client.post("/v1/backtests", headers={
                "X-QF-Session-ID": "a" * 30,
            }, json={
                "symbol": "300007", "exchange": "SZSE",
                "start": "2026-01-01", "end": "2026-01-31",
                "interval": 5, "fast_window": 10, "slow_window": 30,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bars"], 42)
        authorize.assert_called_once_with("a" * 30, "300007", "SZSE")
        config = run.call_args.args[0]
        self.assertEqual(config.start, datetime(2026, 1, 1))
        self.assertEqual(config.end.date(), date(2026, 1, 31))

    def test_invalid_windows_do_not_query_data(self) -> None:
        with patch("BacktestService.service._auth_session") as authorize:
            response = self.client.post("/v1/backtests", headers={
                "X-QF-Session-ID": "a" * 30,
            }, json={
                "symbol": "300007", "exchange": "SZSE",
                "start": "2026-01-01", "end": "2026-01-31",
                "fast_window": 30, "slow_window": 10,
            })
        self.assertEqual(response.status_code, 422)
        authorize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
