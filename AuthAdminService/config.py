"""Runtime configuration for the authorization service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    internal_key: str
    auth_mode: str
    oidc_issuer: str
    oidc_audience: str
    session_ttl_seconds: int
    default_domain: str
    dev_admin_username: str
    dev_admin_password: str
    dev_account: str

    @classmethod
    def from_environment(cls) -> "Settings":
        data_path = REPO_ROOT / "runtime" / "data" / "auth_admin.db"
        settings = cls(
            database_url=os.getenv("QF_AUTH_DATABASE_URL", f"sqlite:///{data_path}"),
            internal_key=os.getenv("QF_AUTH_INTERNAL_KEY", ""),
            auth_mode=os.getenv("QF_AUTH_MODE", "development").lower(),
            oidc_issuer=os.getenv("QF_OIDC_ISSUER", ""),
            oidc_audience=os.getenv("QF_OIDC_AUDIENCE", "quantfabric"),
            session_ttl_seconds=int(os.getenv("QF_AUTH_SESSION_TTL_SECONDS", "900")),
            default_domain=os.getenv("QF_AUTH_DEFAULT_DOMAIN", "desk:cn_equity"),
            dev_admin_username=os.getenv("QF_AUTH_DEV_ADMIN_USERNAME", "admin"),
            dev_admin_password=os.getenv("QF_AUTH_DEV_ADMIN_PASSWORD", ""),
            dev_account=os.getenv("QF_AUTH_DEV_ACCOUNT", "610000071840"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.auth_mode not in {"development", "oidc"}:
            raise RuntimeError("QF_AUTH_MODE must be development or oidc")
        if not self.internal_key:
            raise RuntimeError("QF_AUTH_INTERNAL_KEY must be set")
        if self.session_ttl_seconds <= 0:
            raise RuntimeError("QF_AUTH_SESSION_TTL_SECONDS must be greater than zero")
        if self.auth_mode == "oidc" and not self.oidc_issuer:
            raise RuntimeError("QF_OIDC_ISSUER must be set when QF_AUTH_MODE=oidc")
        if self.database_url.startswith("sqlite:///"):
            database_path = self.database_url[len("sqlite:///"):]
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
