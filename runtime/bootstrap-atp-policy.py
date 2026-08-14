#!/usr/bin/env python3
"""首次启动时通过 BusinessAdmin API 发布标准 ATP 业务配置。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "runtime" / "config" / "ATPBusinessPolicy.json"
BASE_URL = os.getenv("QF_BUSINESS_POLICY_URL", "http://127.0.0.1:19080").rstrip("/")


def request(path: str, method: str = "GET", payload: dict | None = None,
            session_id: str = "") -> dict | str:
    headers = {}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if session_id:
        headers["X-QF-Session-ID"] = session_id
    req = Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            content = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"BusinessAdmin API {method} {path} failed: {exc.code} {detail}") from exc
    return json.loads(content) if content else {}


def resource_key(resource: str, item: dict) -> str:
    fields = {
        "markets": ("market_code",),
        "colocations": ("colo_id",),
        "products": ("fund_id",),
        "projects": ("project_id",),
        "accounts": ("account_id",),
        "account-links": ("project_id", "account_id", "account_type"),
        "securities": ("market_code", "symbol"),
    }[resource]
    return ":".join(str(item[field]) for field in fields)


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    username = os.getenv("QF_AUTH_DEV_ADMIN_USERNAME", "admin")
    password = os.getenv("QF_AUTH_DEV_ADMIN_PASSWORD", "")
    login = request("/v1/sessions/development", "POST", {"username": username, "password": password})
    session_id = str(login["session_id"])
    versions = request("/v1/config/versions", session_id=session_id)
    if any(item.get("status") == "PUBLISHED" for item in versions):
        print("published business policy already exists; bootstrap skipped")
        return 0

    created = request("/v1/config/versions", "POST", {"description": policy["description"]}, session_id)
    version = int(created["version"])
    for resource in ("markets", "colocations", "products", "projects", "accounts",
                     "account-links", "securities"):
        for item in policy[resource]:
            key = quote(resource_key(resource, item), safe=":")
            request(f"/v1/config/{resource}/{key}?version={version}", "PUT", item, session_id)

    validation = request(f"/v1/config/versions/{version}/validate", session_id=session_id)
    if not validation.get("valid"):
        raise RuntimeError(f"ATP business policy validation failed: {validation['issues']}")
    published = request(f"/v1/config/versions/{version}/publish", "POST", session_id=session_id)
    print(f"published ATP business policy version {published['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
