"""Contract tests for the versioned business control plane."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from AuthAdminService.config import Settings as AuthSettings
from AuthAdminService.service import create_app as create_auth_app
from BusinessAdminService.config import Settings
from BusinessAdminService.service import create_app


class BusinessControlPlaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        auth_settings = AuthSettings(
            database_url=f"sqlite:///{Path(self.temp_dir.name) / 'auth.db'}",
            internal_key="test-internal-key",
            auth_mode="development",
            oidc_issuer="",
            oidc_audience="quantfabric",
            session_ttl_seconds=300,
            default_domain="desk:cn_equity",
            dev_admin_username="admin",
            dev_admin_password="test-password",
            dev_account="610000071840",
        )
        self.auth_client = TestClient(create_auth_app(auth_settings))
        settings = Settings(
            database_url=f"sqlite:///{Path(self.temp_dir.name) / 'business.db'}",
            auth_url="http://127.0.0.1:18080",
            auth_internal_key="test-internal-key",
            domain="desk:cn_equity",
            market_data_url="",
            market_data_schema="tdx_init_test",
            market_data_table="stkprice_1min",
            history_service_url="http://127.0.0.1:18081",
        )
        self.client = TestClient(create_app(settings))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def auth_urlopen(self, request, timeout=5):
        if "18080" not in request.full_url:
            from urllib.error import URLError
            raise URLError("test history service unavailable")
        path = request.full_url.split("18080", 1)[1]
        body = request.data.decode("utf-8") if request.data else "{}"
        headers = dict(request.header_items())
        response = self.auth_client.request(request.method, path, data=body, headers=headers)

        class ResponseAdapter:
            def __enter__(self_nonlocal):
                return self_nonlocal

            def __exit__(self_nonlocal, exc_type, exc, tb):
                return None

            def read(self_nonlocal):
                return response.content

        if response.status_code >= 400:
            from urllib.error import HTTPError
            import io
            raise HTTPError(request.full_url, response.status_code, "error", headers, io.BytesIO(response.content))
        return ResponseAdapter()

    def login(self) -> dict:
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            response = self.client.post("/v1/sessions/development", json={"username": "admin", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_health_and_login(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        session = self.login()
        self.assertEqual(session["actor"], "user:admin")

    def test_create_validate_and_publish_version(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            version = self.client.post("/v1/config/versions", headers=headers, json={"description": "base draft"}).json()["version"]
            self.client.put(f"/v1/config/markets/S?version={version}", headers=headers, json={
                "market_code": "S", "exchange_code": "SZSE", "name": "深市", "full_name": "深圳证券交易所", "enabled": True, "remark": ""
            })
            self.client.put(f"/v1/config/colocations/1000?version={version}", headers=headers, json={
                "colo_id": 1000, "name": "国信", "full_name": "国信东莞", "enabled": True
            })
            self.client.put(f"/v1/config/products/1?version={version}", headers=headers, json={
                "fund_id": 1, "fund_code": "P001", "name": "测试产品", "full_name": "测试产品全称",
                "allowed_security_types": "A", "allowed_directions": "A", "allowed_markets": "S",
                "fund_type": "EQ", "valuation_type": "1", "bond_risk_value": "1", "long_stop_value": "1", "status": "1"
            })
            self.client.put(f"/v1/config/projects/1?version={version}", headers=headers, json={
                "project_id": 1, "name": "资产一", "fund_id": 1, "initial_balance": 1000000,
                "project_type": "0", "hedge_flags": "0", "default_flag": True, "enabled": True, "remark": ""
            })
            self.client.put(f"/v1/config/accounts/188795?version={version}", headers=headers, json={
                "account_id": "188795", "broker_id": "GX", "broker_name": "国信", "account_type": "0",
                "initial_balance": 1000000, "colo_id": 1000, "open_date": "20260812", "status": "1"
            })
            self.client.put(f"/v1/config/account-links/1:188795:0?version={version}", headers=headers, json={
                "project_id": 1, "account_id": "188795", "account_type": "0", "default_flag": True,
                "external_account_id": "", "fund_id": 1
            })
            self.client.put(f"/v1/config/securities/S:000001?version={version}", headers=headers, json={
                "market_code": "S", "symbol": "000001", "name": "平安银行", "security_type": "A",
                "exchange_symbol": "000001", "suspended": False, "buy_allowed": True, "sell_allowed": True,
                "cancel_allowed": True, "price_tick": "0.01", "buy_unit": 100, "sell_unit": 100,
                "max_quantity": 10000, "min_quantity": 100
            })
            result = self.client.get(f"/v1/config/versions/{version}/validate", headers=headers)
            self.assertTrue(result.json()["valid"])
            publish = self.client.post(f"/v1/config/versions/{version}/publish", headers=headers)
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()["status"], "PUBLISHED")
        runtime_policy = self.client.get("/v1/internal/config/published/runtime-policy",
                                         headers={"X-QF-Internal-Key": "test-internal-key"})
        self.assertEqual(runtime_policy.status_code, 200)
        self.assertEqual(runtime_policy.text.splitlines()[0], "QF_RUNTIME_POLICY\t1")
        self.assertIn(f"VERSION\t{version}", runtime_policy.text)
        self.assertIn("MARKET\tS\tSZSE\t1", runtime_policy.text)
        self.assertIn("PROJECT\t1\t1\t1", runtime_policy.text)
        self.assertIn("ACCOUNT\t188795\t0\t1", runtime_policy.text)
        self.assertIn("LINK\t1\t188795\t0\t1\t1", runtime_policy.text)
        self.assertIn("SECURITY\tS\t000001\t0\t1\t1\t1\t0.0100\t100\t100\t10000\t100", runtime_policy.text)

    def test_publish_requires_successful_validation(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            version = self.client.post("/v1/config/versions", headers=headers,
                                       json={"description": "unvalidated draft"}).json()["version"]
            response = self.client.post(f"/v1/config/versions/{version}/publish", headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("validated", response.json()["detail"])

    def test_validation_requires_default_account_for_enabled_project(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            version = self.client.post("/v1/config/versions", headers=headers,
                                       json={"description": "missing default account"}).json()["version"]
            self.client.put(f"/v1/config/markets/S?version={version}", headers=headers, json={
                "market_code": "S", "exchange_code": "SZSE", "name": "深市", "full_name": "深圳证券交易所",
                "enabled": True, "remark": ""
            })
            self.client.put(f"/v1/config/products/1?version={version}", headers=headers, json={
                "fund_id": 1, "fund_code": "P001", "name": "测试产品", "full_name": "",
                "allowed_security_types": "A", "allowed_directions": "A", "allowed_markets": "S",
                "fund_type": "EQ", "valuation_type": "1", "bond_risk_value": "1", "long_stop_value": "1", "status": "1"
            })
            self.client.put(f"/v1/config/projects/1?version={version}", headers=headers, json={
                "project_id": 1, "name": "资产一", "fund_id": 1, "initial_balance": 1000000,
                "project_type": "0", "hedge_flags": "0", "default_flag": True, "enabled": True, "remark": ""
            })
            response = self.client.get(f"/v1/config/versions/{version}/validate", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valid"])
        self.assertIn("默认资金账户", str(response.json()["issues"]))

    def test_draft_can_copy_retired_version_but_not_another_draft(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            first = self.client.post("/v1/config/versions", headers=headers,
                                     json={"description": "first draft"}).json()["version"]
            second = self.client.post("/v1/config/versions", headers=headers,
                                      json={"description": "must not copy draft", "source_version": first})
        self.assertEqual(second.status_code, 409)
        self.assertIn("published or retired", second.json()["detail"])

    def test_validation_rejects_missing_product_reference(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            version = self.client.post("/v1/config/versions", headers=headers, json={"description": "bad draft"}).json()["version"]
            self.client.put(f"/v1/config/projects/2?version={version}", headers=headers, json={
                "project_id": 2, "name": "资产二", "fund_id": 99, "initial_balance": 100,
                "project_type": "0", "hedge_flags": "0", "default_flag": False, "enabled": True, "remark": ""
            })
            result = self.client.get(f"/v1/config/versions/{version}/validate", headers=headers)
        self.assertFalse(result.json()["valid"])
        self.assertIn("产品 99 不存在", str(result.json()["issues"]))

    def test_market_data_summary_without_database_is_explicit(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            response = self.client.get("/v1/market-data/summary", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])

    def test_market_data_summary_reads_aggregate_from_history_service(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}

        def urlopen_for_summary(request, timeout=5):
            if "18080" in request.full_url:
                return self.auth_urlopen(request, timeout)
            self.assertEqual(request.full_url, "http://127.0.0.1:18081/v1/internal/summary")
            self.assertEqual(dict(request.header_items())["X-qf-internal-key"], "test-internal-key")

            class ResponseAdapter:
                def __enter__(self_nonlocal):
                    return self_nonlocal

                def __exit__(self_nonlocal, exc_type, exc, tb):
                    return None

                def read(self_nonlocal):
                    return json.dumps({
                        "backend": "clickhouse",
                        "source": "tdxdata.stkprice_1min",
                        "rows": 174658977,
                        "first_time": "2021-08-16 09:31:00",
                        "last_time": "2026-08-11 15:00:00",
                    }).encode("utf-8")

            return ResponseAdapter()

        with patch("BusinessAdminService.service.urlopen", side_effect=urlopen_for_summary):
            response = self.client.get("/v1/market-data/summary", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertEqual(response.json()["table"], "tdxdata.stkprice_1min")
        self.assertEqual(response.json()["rows"], 174658977)

    def test_internal_published_config_requires_service_key(self) -> None:
        self.assertEqual(self.client.get("/v1/internal/config/published").status_code, 401)

    def test_casbin_denies_business_read_for_ungranted_operator(self) -> None:
        admin_session = self.auth_client.post("/v1/sessions/development", json={
            "username": "admin", "password": "test-password",
        }).json()["session_id"]
        created = self.auth_client.post("/v1/admin/identities", headers={
            "X-QF-Session-ID": admin_session,
        }, json={
            "username": "viewer", "display_name": "Read denied operator", "password": "viewer-password",
        })
        self.assertEqual(created.status_code, 200)
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            viewer_session = self.client.post("/v1/sessions/development", json={
                "username": "viewer", "password": "viewer-password",
            }).json()["session_id"]
            response = self.client.get("/v1/config/versions", headers={
                "X-QF-Session-ID": viewer_session,
            })
        self.assertEqual(response.status_code, 403)

    def test_business_audit_tracks_version_write(self) -> None:
        session = self.login()
        headers = {"X-QF-Session-ID": session["session_id"]}
        with patch("BusinessAdminService.service.urlopen", side_effect=self.auth_urlopen):
            version = self.client.post("/v1/config/versions", headers=headers,
                                       json={"description": "audit draft"}).json()["version"]
            audit = self.client.get(f"/v1/audit?version={version}", headers=headers)
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(item["action"] == "business:write" and
                            item["resource"] == "config-version"
                            for item in audit.json()["items"]))


if __name__ == "__main__":
    unittest.main()
