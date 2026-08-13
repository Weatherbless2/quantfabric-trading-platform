import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from HistoryDataService.service import _number, create_app


class HistoryContractTest(unittest.TestCase):
    def test_health_without_database_is_explicit(self) -> None:
        with patch("HistoryDataService.service.DATABASE_URL", ""):
            response = TestClient(create_app()).get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "missing")

    def test_symbol_and_exchange_are_validated_before_database_access(self) -> None:
        with patch("HistoryDataService.service._auth_session") as authorize, \
                patch("HistoryDataService.service._connection") as connection:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=00001&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 422)
        authorize.assert_not_called()
        connection.assert_not_called()

    def test_history_permission_is_required_before_database_access(self) -> None:
        with patch("HistoryDataService.service._auth_session", side_effect=Exception("denied")), \
                patch("HistoryDataService.service._connection") as connection:
            with self.assertRaises(Exception):
                TestClient(create_app()).get(
                    "/v1/history/minute?symbol=000014&exchange=SZSE",
                    headers={"X-QF-Session-ID": "a" * 30},
                )
        connection.assert_not_called()

    def test_five_minute_history_is_aggregated_in_order(self) -> None:
        rows = [
            {"trdtime": datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc), "open": Decimal("10"),
             "high": Decimal("11"), "low": Decimal("9"), "close": Decimal("10.5"),
             "vol": Decimal("100"), "amt": Decimal("1000")},
            {"trdtime": datetime(2026, 8, 12, 9, 34, tzinfo=timezone.utc), "open": Decimal("10.5"),
             "high": Decimal("12"), "low": Decimal("10"), "close": Decimal("11.8"),
             "vol": Decimal("200"), "amt": Decimal("2200")},
        ]
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchall.return_value = list(reversed(rows))
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._connection", return_value=connection):
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE&interval=5&limit=5",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 200)
        bar = response.json()["bars"][0]
        self.assertEqual(bar["open"], 10)
        self.assertEqual(bar["high"], 12)
        self.assertEqual(bar["low"], 9)
        self.assertEqual(bar["close"], 11.8)
        self.assertEqual(bar["volume"], 300)
        self.assertEqual(bar["turnover"], 3200)
        parameters = connection.__enter__.return_value.execute.call_args.args[1]
        self.assertEqual(parameters[:2], ("S", "SZSE:000014"))
        executed_limit = parameters[2]
        self.assertEqual(executed_limit, 30)

    def test_source_mapping_is_configurable_without_changing_the_api(self) -> None:
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchall.return_value = []
        with patch.dict(os.environ, {
            "QF_HISTORY_MARKET_CODES": "SSE=H,SZSE=Z",
            "QF_HISTORY_SYMBOL_TEMPLATE": "{symbol}",
        }), patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._connection", return_value=connection):
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 200)
        parameters = connection.__enter__.return_value.execute.call_args.args[1]
        self.assertEqual(parameters[:2], ("Z", "000014"))

    def test_database_outage_returns_only_a_short_lived_authorized_cache(self) -> None:
        rows = [{"trdtime": datetime(2026, 8, 12, 9, 30), "open": Decimal("10"),
                 "high": Decimal("11"), "low": Decimal("9"), "close": Decimal("10.5"),
                 "vol": Decimal("100"), "amt": Decimal("1000")}]
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchall.return_value = rows
        app = create_app()
        client = TestClient(app)
        request = "/v1/history/minute?symbol=000014&exchange=SZSE"
        headers = {"X-QF-Session-ID": "a" * 30}
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._connection", return_value=connection):
            self.assertFalse(client.get(request, headers=headers).json()["stale"])
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._connection", side_effect=OSError("database unavailable")):
            response = client.get(request, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["stale"])
        self.assertEqual(response.json()["bars"][0]["close"], 10.5)

    def test_request_is_rejected_when_source_bar_limit_is_insufficient(self) -> None:
        with patch.dict(os.environ, {"QF_HISTORY_MAX_RAW_BARS": "100"}), \
                patch("HistoryDataService.service._auth_session") as authorize, \
                patch("HistoryDataService.service._connection") as connection:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE&interval=15&limit=10",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("QF_HISTORY_MAX_RAW_BARS", response.json()["detail"])
        authorize.assert_called_once()
        connection.assert_not_called()

    def test_unsupported_interval_is_rejected(self) -> None:
        with patch("HistoryDataService.service._auth_session") as authorize:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE&interval=2",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 400)
        authorize.assert_not_called()

    def test_decimal_number_is_json_safe(self) -> None:
        self.assertEqual(_number(Decimal("18.56")), 18.56)


if __name__ == "__main__":
    unittest.main()
