"""Authorization service contract tests using the SQLite development backend."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from AuthAdminService.config import Settings
from AuthAdminService.schemas import SESSION_ID_LENGTH
from AuthAdminService.service import AuthorizationService, create_app


class AuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
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
        self.client = TestClient(create_app(settings))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def login(self) -> str:
        response = self.client.post("/v1/sessions/development", json={"username": "admin", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        return response.json()["session_id"]

    def test_login_and_authorize_account_order(self) -> None:
        session_id = self.login()
        self.assertEqual(len(session_id), SESSION_ID_LENGTH)
        response = self.client.post("/v1/internal/authorize", headers={"X-QF-Internal-Key": "test-internal-key"}, json={
            "session_id": session_id,
            "domain": "desk:cn_equity",
            "resource": "account/610000071840",
            "action": "order:create",
            "trace_id": "QF-test-1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["allowed"])

    def test_unknown_session_is_denied(self) -> None:
        response = self.client.post("/v1/internal/authorize", headers={"X-QF-Internal-Key": "test-internal-key"}, json={
            "session_id": "0" * SESSION_ID_LENGTH,
            "domain": "desk:cn_equity",
            "resource": "account/610000071840",
            "action": "order:create",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["allowed"])

    def test_internal_endpoint_requires_service_key(self) -> None:
        response = self.client.get("/v1/internal/sessions/" + "0" * 32)
        self.assertEqual(response.status_code, 401)

    def test_policy_and_role_binding_management(self) -> None:
        session_id = self.login()
        headers = {"X-QF-Session-ID": session_id}
        role = {"subject": "user:operator", "role": "role:trader", "domain": "desk:cn_equity"}
        policy = {
            "subject": "role:trader",
            "domain": "desk:cn_equity",
            "resource": "account/610000071840",
            "action": "order:read",
        }

        response = self.client.post("/v1/admin/role-bindings", headers=headers, json=role)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        response = self.client.post("/v1/admin/policies", headers=headers, json=policy)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])

        response = self.client.get("/v1/admin/role-bindings", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(["user:operator", "role:trader", "desk:cn_equity"], response.json()["items"])
        response = self.client.get("/v1/admin/policies", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(["role:trader", "desk:cn_equity", "account/610000071840", "order:read"], response.json()["items"])

        self.assertTrue(self.client.request("DELETE", "/v1/admin/policies", headers=headers, json=policy).json()["changed"])
        self.assertTrue(self.client.request("DELETE", "/v1/admin/role-bindings", headers=headers, json=role).json()["changed"])

    def test_policy_management_requires_a_valid_session(self) -> None:
        response = self.client.get("/v1/admin/policies", headers={"X-QF-Session-ID": "0" * SESSION_ID_LENGTH})
        self.assertEqual(response.status_code, 403)

    def test_oidc_roles_are_restricted_to_safe_role_names(self) -> None:
        roles = AuthorizationService._oidc_roles({
            "realm_access": {"roles": ["trader", "risk:update", "bad role", 12, "role/invalid"]}
        })
        self.assertEqual(roles, ("role:risk:update", "role:trader"))


if __name__ == "__main__":
    unittest.main()
