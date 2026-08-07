#!/usr/bin/env python3
"""ATP 连接与只读查询诊断程序。

该程序刻意不实现报单和撤单接口，用于先确认 SDK、AGW、客户登录及查询链路。
"""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ATP_DIR = ROOT_DIR / "AtpTraderOfGuosen(1)"
ATP_LIB_DIR = ATP_DIR / "pylib" / "linux64"
sys.path.insert(0, str(ATP_LIB_DIR))

try:
    from atptradeapi_py import ATPTradeAPI, ATPTradeHandler
except ImportError as exc:
    raise SystemExit(
        "ATP SDK 加载失败，请通过 runtime/atp-diagnose.sh 启动，以设置动态库路径: "
        f"{exc}"
    ) from exc


SUCCESS_CODE = 10000


class Sequence:
    """为一次 ATP 会话生成单调递增的 client_seq_id。"""

    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            self._value += 1
            return self._value


class ReadOnlyHandler(ATPTradeHandler):
    def __init__(self):
        super().__init__()
        self.agw_login = threading.Event()
        self.customer_login = threading.Event()
        self.query_events = {
            "fund": threading.Event(),
            "position": threading.Event(),
            "order": threading.Event(),
            "trade": threading.Event(),
        }
        self.failed_reason = None

    @staticmethod
    def _emit(event, data):
        # 回调对象可能包含 bytes，default=str 保证诊断输出始终是一行合法 JSON。
        print(json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str), flush=True)

    def OnLogin(self, reason):
        self._emit("agw_login", {"reason": reason})
        self.agw_login.set()

    def OnRecovered(self, reason):
        self._emit("agw_recovered", {"reason": reason})
        self.agw_login.set()

    def OnConnected(self, reason):
        self._emit("agw_connected", {"reason": reason})

    def OnClosed(self, reason):
        self.failed_reason = reason
        self._emit("agw_closed", {"reason": reason})

    def OnConnectFailure(self, reason):
        self.failed_reason = reason
        self._emit("agw_connect_failure", {"reason": reason})

    def OnConnectTimeOut(self, reason):
        self.failed_reason = reason
        self._emit("agw_connect_timeout", {"reason": reason})

    def OnError(self, reason):
        self._emit("agw_error", {"reason": reason})

    def OnRspCustLoginResp(self, data):
        self._emit("customer_login", data)
        if data.get("permisson_error_code", -1) == 0:
            self.customer_login.set()
        else:
            self.failed_reason = data.get("reject_desc", "客户登录失败")

    def OnRspCustLogoutResp(self, data):
        self._emit("customer_logout", data)

    def OnRspFundQueryResult(self, data):
        self._emit("fund", data)
        self.query_events["fund"].set()

    def OnRspShareQueryResult(self, data):
        self._emit("position", data)
        self.query_events["position"].set()

    def OnRspOrderQueryResult(self, data):
        self._emit("order", data)
        self.query_events["order"].set()

    def OnRspTradeOrderQueryResult(self, data):
        self._emit("trade", data)
        self.query_events["trade"].set()


def load_config(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def require_success(operation, result):
    if result.get("err_code") != SUCCESS_CODE:
        raise RuntimeError(f"{operation} 请求未被 ATP 接受: {result}")
    print(json.dumps({"event": "request_accepted", "operation": operation, "data": result}), flush=True)


def wait_for(event, name, timeout, handler):
    if event.wait(timeout):
        return
    reason = f": {handler.failed_reason}" if handler.failed_reason else ""
    raise TimeoutError(f"等待{name}超时（{timeout} 秒）{reason}")


def account_request(config, sequence):
    account = config["account"]
    return {
        "cust_id": account["customer_id"],
        "fund_account_id": account["fund_account_id"],
        "account_id": account["shenzhen_account_id"],
        "branch_id": account["branch_id"],
        "client_seq_id": sequence.next(),
    }


def run_queries(api, handler, config, sequence, timeout):
    requests = (
        ("fund", api.ReqFundQuery, {}),
        ("position", api.ReqShareQuery, {"return_num": 0}),
        ("order", api.ReqOrderQuery, {"business_abstract_type": 1}),
        ("trade", api.ReqTradeOrderQuery, {"business_abstract_type": 1}),
    )
    for name, method, extra in requests:
        request = account_request(config, sequence)
        request.update(extra)
        require_success(name, method(request))
        wait_for(handler.query_events[name], f"{name} 查询回调", timeout, handler)


def main():
    parser = argparse.ArgumentParser(description="ATP 只读登录和查询诊断")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    config = load_config(args.config)
    log_dir = ROOT_DIR / "runtime" / "log" / "atp"
    log_dir.mkdir(parents=True, exist_ok=True)
    encrypt_config = {
        "ENCRYPT_SCHEMA": "0",
        "ATP_ENCRYPT_PASSWORD": "",
        "ATP_LOGIN_ENCRYPT_PASSWORD": "",
        "GM_SM2_PUBLIC_KEY_PATH": "",
        "RSA_PUBLIC_KEY_PATH": "",
    }

    init_result = ATPTradeAPI.Init("", str(ATP_LIB_DIR), str(log_dir), True, encrypt_config, 1, False)
    require_success("sdk_init", init_result)

    api = ATPTradeAPI()
    handler = ReadOnlyHandler()
    sequence = Sequence()
    agw = config["agw"]
    connect_config = {
        "user": agw["user"],
        "password": agw["password"],
        "locations": agw["locations"],
        "heartbeat_interval_milli": 5000,
        "connect_timeout_milli": int(args.timeout * 1000),
        "reconnect_time": 10,
        "client_name": "quantfabric_atp_bridge",
        "client_version": "v0.1",
        "mode": 1,
        "report_sync": {},
    }

    try:
        require_success("agw_connect", api.Connect(connect_config, handler))
        wait_for(handler.agw_login, "AGW 登录", args.timeout, handler)

        login_request = account_request(config, sequence)
        login_request.update({"password": config["account"]["encrypted_password"], "login_mode": 1})
        require_success("customer_login", api.ReqCustLoginOther(login_request))
        wait_for(handler.customer_login, "客户登录", args.timeout, handler)

        run_queries(api, handler, config, sequence, args.timeout)
        print(json.dumps({"event": "diagnostic_complete", "readonly": True}), flush=True)
    finally:
        if handler.customer_login.is_set():
            logout = {
                "cust_id": config["account"]["customer_id"],
                "fund_account_id": config["account"]["fund_account_id"],
                "client_seq_id": sequence.next(),
            }
            result = api.ReqCustLogoutOther(logout)
            print(json.dumps({"event": "logout_requested", "data": result}), flush=True)
            time.sleep(0.5)
        api.Stop()
        api.Close()


if __name__ == "__main__":
    main()
