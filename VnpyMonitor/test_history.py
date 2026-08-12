import unittest
from unittest.mock import patch

from VnpyMonitor.history import HistoryLoader


class HistoryClientContractTest(unittest.TestCase):
    def test_request_contains_symbol_exchange_interval_and_limit(self) -> None:
        with patch("VnpyMonitor.history.urlopen") as mocked_open:
            mocked_open.return_value.__enter__.return_value.read.return_value = b'{"bars": []}'
            loaded = []
            worker = HistoryLoader("http://history", "a" * 30, "000014.SZSE", 5, 120)
            worker.loaded.connect(lambda symbol, interval, bars: loaded.append((symbol, interval, bars)))
            worker.run()
        request = mocked_open.call_args.args[0]
        self.assertIn("symbol=000014", request.full_url)
        self.assertIn("exchange=SZSE", request.full_url)
        self.assertIn("interval=5", request.full_url)
        self.assertIn("limit=120", request.full_url)
        self.assertEqual(loaded, [("000014.SZSE", 5, [])])

    def test_timezone_aware_timestamp_is_normalized(self) -> None:
        bar = HistoryLoader._parse_bar({
            "datetime": "2026-08-12T09:30:00+00:00",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
        })
        self.assertIsNone(bar.datetime.tzinfo)
        self.assertEqual(bar.close_price, 10.5)


if __name__ == "__main__":
    unittest.main()
