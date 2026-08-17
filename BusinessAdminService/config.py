"""Environment-backed configuration for the business control plane."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    auth_url: str
    auth_internal_key: str
    domain: str
    market_data_url: str
    market_data_schema: str
    market_data_table: str
    history_service_url: str
    reconciliation_path: str = str(REPO_ROOT / "runtime" / "data" / "atp-reconciliation.jsonl")

    @classmethod
    def from_environment(cls) -> "Settings":
        data_path = REPO_ROOT / "runtime" / "data" / "business_admin.db"
        settings = cls(
            database_url=os.getenv("QF_BUSINESS_DATABASE_URL", f"sqlite:///{data_path}"),
            auth_url=os.getenv("QF_BUSINESS_AUTH_URL", "http://127.0.0.1:18080").rstrip("/"),
            auth_internal_key=os.getenv("QF_AUTH_INTERNAL_KEY", ""),
            domain=os.getenv("QF_BUSINESS_DOMAIN", "desk:cn_equity"),
            market_data_url=os.getenv("QF_MARKET_DATA_DATABASE_URL", ""),
            market_data_schema=os.getenv("QF_MARKET_DATA_SCHEMA", "tdx_init_test"),
            market_data_table=os.getenv("QF_MARKET_DATA_TABLE", "stkprice_1min"),
            history_service_url=os.getenv("QF_HISTORY_SERVICE_URL", "http://127.0.0.1:18081").rstrip("/"),
            reconciliation_path=os.getenv(
                "QF_ATP_RECONCILIATION_PATH",
                str(REPO_ROOT / "runtime" / "data" / "atp-reconciliation.jsonl"),
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.database_url:
            raise RuntimeError("QF_BUSINESS_DATABASE_URL must be configured")
        if not self.auth_url:
            raise RuntimeError("QF_BUSINESS_AUTH_URL must be configured")
        if not self.history_service_url.startswith(("http://", "https://")):
            raise RuntimeError("QF_HISTORY_SERVICE_URL must be an http(s) URL")
        if not self.reconciliation_path:
            raise RuntimeError("QF_ATP_RECONCILIATION_PATH must be configured")
        if not self.auth_internal_key:
            raise RuntimeError("QF_AUTH_INTERNAL_KEY must be configured")
        for value, label in ((self.market_data_schema, "QF_MARKET_DATA_SCHEMA"),
                             (self.market_data_table, "QF_MARKET_DATA_TABLE")):
            if value and (not value.replace("_", "").isalnum() or not value[0].isalpha()):
                raise RuntimeError(f"{label} must be a simple SQL identifier")
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
