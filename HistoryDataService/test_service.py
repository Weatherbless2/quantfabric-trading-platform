import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from HistoryDataService.service import (
    DEFAULT_BACKEND,
    DEFAULT_CLICKHOUSE_DATABASE,
    HistorySource,
    _clickhouse_rows,
    _clickhouse_query,
    _source_summary,
    _number,
    create_app,
)


def _rows() -> list[dict[str, object]]:
    return [
        {"trdtime": datetime(2026, 8, 12, 9, 34, tzinfo=timezone.utc), "open": Decimal("10.5"),
         "high": Decimal("12"), "low": Decimal("10"), "close": Decimal("11.8"),
         "vol": Decimal("200"), "amt": Decimal("2200")},
        {"trdtime": datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc), "open": Decimal("10"),
         "high": Decimal("11"), "low": Decimal("9"), "close": Decimal("10.5"),
         "vol": Decimal("100"), "amt": Decimal("1000")},
    ]


class HistoryContractTest(unittest.TestCase):
    def test_default_source_is_tdxdata_clickhouse(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = HistorySource.from_environment()
        self.assertEqual(source.backend, DEFAULT_BACKEND)
        self.assertEqual(source.clickhouse_database, DEFAULT_CLICKHOUSE_DATABASE)
        self.assertEqual(source.instrument("000014", "SZSE"), ("S", "SZSE:000014"))

    def test_health_reports_missing_clickhouse_credentials_without_exposing_them(self) -> None:
        with patch.dict(os.environ, {
            "QF_HISTORY_CLICKHOUSE_USERNAME": "",
            "QF_HISTORY_CLICKHOUSE_PASSWORD": "",
        }, clear=True):
            response = TestClient(create_app()).get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backend"], "clickhouse")
        self.assertEqual(response.json()["database"], "missing")
        self.assertNotIn("password", response.text.lower())

    def test_symbol_and_exchange_are_validated_before_data_access(self) -> None:
        with patch("HistoryDataService.service._auth_session") as authorize, \
                patch("HistoryDataService.service._fetch_rows") as fetch_rows:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=00001&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 422)
        authorize.assert_not_called()
        fetch_rows.assert_not_called()

    def test_history_permission_is_required_before_data_access(self) -> None:
        with patch("HistoryDataService.service._auth_session",
                   side_effect=HTTPException(status_code=403, detail="denied")), \
                patch("HistoryDataService.service._fetch_rows") as fetch_rows:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 403)
        fetch_rows.assert_not_called()

    def test_five_minute_history_is_aggregated_in_order(self) -> None:
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._fetch_rows", return_value=_rows()) as fetch_rows:
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
        source, market, stock_code, raw_limit = fetch_rows.call_args.args
        self.assertEqual(source.backend, "clickhouse")
        self.assertEqual((market, stock_code, raw_limit), ("S", "SZSE:000014", 30))

    def test_source_mapping_is_configurable_without_changing_the_api(self) -> None:
        with patch.dict(os.environ, {
            "QF_HISTORY_MARKET_CODES": "SSE=H,SZSE=Z",
            "QF_HISTORY_SYMBOL_TEMPLATE": "{symbol}",
        }), patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._fetch_rows", return_value=[]) as fetch_rows:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fetch_rows.call_args.args[1:3], ("Z", "000014"))

    def test_clickhouse_uses_basic_auth_and_bound_parameters(self) -> None:
        source = HistorySource.from_environment()
        source = HistorySource(
            **{**source.__dict__, "clickhouse_username": "readonly", "clickhouse_password": "not-in-url"})
        response = MagicMock()
        response.read.return_value = b'{"value":"1"}\n'
        response.__enter__.return_value = response
        with patch("HistoryDataService.service.urlopen", return_value=response) as mocked_open:
            _clickhouse_query(source, "SELECT {symbol:String}", {"symbol": "000014"})
        request = mocked_open.call_args.args[0]
        self.assertIn("param_symbol=000014", request.full_url)
        self.assertNotIn("not-in-url", request.full_url)
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertNotIn("not-in-url", request.data.decode("utf-8"))

    def test_clickhouse_json_rows_are_parsed_before_aggregation(self) -> None:
        source = HistorySource.from_environment()
        source = HistorySource(
            **{**source.__dict__, "clickhouse_username": "readonly", "clickhouse_password": "secret"})
        payload = (
            '{"trdtime":"2026-08-12 09:34:00","open":"10.5","high":"12",'
            '"low":"10","close":"11.8","vol":"200","amt":"2200"}\n'
        )
        with patch("HistoryDataService.service._clickhouse_query", return_value=payload):
            rows = _clickhouse_rows(source, "S", "SZSE:000014", 6)
        self.assertEqual(rows[0]["trdtime"], datetime(2026, 8, 12, 9, 34))
        self.assertEqual(_number(rows[0]["close"]), 11.8)

    def test_clickhouse_summary_is_parsed_without_exposing_credentials(self) -> None:
        source = HistorySource.from_environment()
        source = HistorySource(
            **{**source.__dict__, "clickhouse_username": "readonly", "clickhouse_password": "secret"})
        with patch("HistoryDataService.service._clickhouse_query", return_value=(
                '{"rows":"42","first_time":"2026-08-01 09:31:00",'
                '"last_time":"2026-08-01 15:00:00"}\n')):
            summary = _source_summary(source)
        self.assertEqual(summary["source"], "tdxdata.stkprice_1min")
        self.assertEqual(summary["rows"], 42)

    def test_internal_summary_requires_the_service_key(self) -> None:
        with patch("HistoryDataService.service.AUTH_INTERNAL_KEY", "internal-key"), \
                patch("HistoryDataService.service._source_summary", return_value={"rows": 1}):
            client = TestClient(create_app())
            self.assertEqual(client.get("/v1/internal/summary").status_code, 401)
            response = client.get("/v1/internal/summary", headers={
                "X-QF-Internal-Key": "internal-key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], 1)

    def test_database_outage_returns_only_a_short_lived_authorized_cache(self) -> None:
        app = create_app()
        client = TestClient(app)
        request = "/v1/history/minute?symbol=000014&exchange=SZSE"
        headers = {"X-QF-Session-ID": "a" * 30}
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._fetch_rows", return_value=_rows()):
            self.assertFalse(client.get(request, headers=headers).json()["stale"])
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._fetch_rows", side_effect=OSError("unavailable")):
            response = client.get(request, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["stale"])
        self.assertEqual(response.json()["bars"][-1]["close"], 11.8)

    def test_data_outage_without_cache_does_not_leak_backend_details(self) -> None:
        with patch("HistoryDataService.service._auth_session"), \
                patch("HistoryDataService.service._fetch_rows", side_effect=OSError("secret endpoint")):
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "history data source unavailable")

    def test_request_is_rejected_when_source_bar_limit_is_insufficient(self) -> None:
        with patch.dict(os.environ, {"QF_HISTORY_MAX_RAW_BARS": "100"}), \
                patch("HistoryDataService.service._auth_session") as authorize, \
                patch("HistoryDataService.service._fetch_rows") as fetch_rows:
            response = TestClient(create_app()).get(
                "/v1/history/minute?symbol=000014&exchange=SZSE&interval=15&limit=10",
                headers={"X-QF-Session-ID": "a" * 30},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("QF_HISTORY_MAX_RAW_BARS", response.json()["detail"])
        authorize.assert_called_once()
        fetch_rows.assert_not_called()

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
