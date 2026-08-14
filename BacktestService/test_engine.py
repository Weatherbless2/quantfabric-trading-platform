import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from .engine import BacktestConfig, run_backtest
from HistoryDataService.service import HistorySource


class BacktestEngineTest(unittest.TestCase):
    def test_postgres_source_is_rejected_explicitly(self) -> None:
        source = HistorySource(
            backend="postgres", schema="tdx", table="bars", clickhouse_url="http://unused",
            clickhouse_database="unused", clickhouse_username="", clickhouse_password="",
            market_codes={"SSE": "S", "SZSE": "S"}, symbol_template="{exchange}:{symbol}",
            max_raw_bars=1000, stale_cache_seconds=0,
        )
        with self.assertRaisesRegex(ValueError, "requires .*clickhouse"):
            run_backtest(BacktestConfig("000001", "SZSE", datetime(2025, 1, 1), datetime(2025, 1, 2)), source)

    def test_signal_uses_next_bar_open_and_closes_position(self) -> None:
        rows = []
        start = datetime(2025, 1, 1, 9, 30)
        closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7]
        for index, close in enumerate(closes):
            timestamp = start + timedelta(minutes=index)
            rows.append(json.dumps({"trdtime": timestamp.isoformat(), "open": close, "high": close, "low": close, "close": close, "vol": 100, "amt": close * 100}))
        with patch("BacktestService.engine._clickhouse_query", return_value="\n".join(rows)):
            result = run_backtest(BacktestConfig("000001", "SZSE", start, start + timedelta(minutes=20), interval=1, fast_window=2, slow_window=3))
        self.assertEqual(result.bars, len(closes))
        self.assertGreaterEqual(len(result.trades), 2)
        self.assertEqual(result.trades[0].side, "buy")
        self.assertEqual(result.trades[-1].side, "sell")


if __name__ == "__main__":
    unittest.main()
