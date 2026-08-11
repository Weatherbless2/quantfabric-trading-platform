#!/usr/bin/env python3
"""将 pytdx 股票快照转换为本机 JSON 行行情流。"""

import argparse
import json
import socket
import sys
import time
import types
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PYTDX_ROOT = ROOT_DIR / "pytdx"


def import_tdx_api():
    """兼容这份源码中的历史包名 OxQuant.pytdx，不修改第三方目录。"""
    sys.path.insert(0, str(PYTDX_ROOT))
    import pytdx

    oxquant = types.ModuleType("OxQuant")
    oxquant.__path__ = []
    oxquant.pytdx = pytdx
    sys.modules.setdefault("OxQuant", oxquant)
    sys.modules.setdefault("OxQuant.pytdx", pytdx)

    from pytdx.hq import TdxHq_API
    return TdxHq_API


def load_config(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


class LocalQuoteServer:
    """向 C++ 行情插件广播行情，并接收同一连接上的订阅命令。"""

    def __init__(self, host, port):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(4)
        self._server.setblocking(False)
        self._clients = {}

    def _accept_clients(self):
        while True:
            try:
                client, _ = self._server.accept()
                client.setblocking(False)
                self._clients[client] = b""
            except BlockingIOError:
                return

    def poll_commands(self, handler):
        self._accept_clients()
        disconnected = []
        for client, pending in list(self._clients.items()):
            try:
                block = client.recv(65536)
            except BlockingIOError:
                continue
            except OSError:
                disconnected.append(client)
                continue
            if not block:
                disconnected.append(client)
                continue
            pending += block
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    handler(json.loads(line.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    print(json.dumps({"event": "subscription_rejected", "error": str(exc)}), flush=True)
            self._clients[client] = pending
        for client in disconnected:
            client.close()
            self._clients.pop(client, None)

    def publish(self, quote):
        self._accept_clients()
        payload = (json.dumps(quote, ensure_ascii=False) + "\n").encode("utf-8")
        disconnected = []
        for client in self._clients:
            try:
                client.sendall(payload)
            except OSError:
                disconnected.append(client)
        for client in disconnected:
            client.close()
            self._clients.pop(client, None)

    def close(self):
        for client in self._clients:
            client.close()
        self._server.close()


def connect(api, servers, timeout):
    failures = []
    for server in servers:
        try:
            if api.connect(server["host"], server["port"], time_out=timeout):
                return server
        except Exception as exc:
            failures.append(f"{server['host']}:{server['port']}={exc}")
    raise ConnectionError("配置中的通达信行情服务器均无法连接: " + "; ".join(failures))


def normalize_quote(raw, security):
    now = datetime.now()
    turnover = raw.get("amount", 0)
    if abs(turnover) < 1e-20:
        turnover = 0
    # pytdx 的买卖盘字段为 bid1/ask1、bid_vol1/ask_vol1，统一为数组供 C++ 映射。
    return {
        "type": "stock_quote",
        "ticker": security["ticker"],
        "name": security.get("name", security["ticker"]),
        "exchange": security["exchange"],
        "update_time": now.strftime("%H:%M:%S"),
        "millisec": now.microsecond // 1000,
        "last_price": raw.get("price", 0),
        "volume": raw.get("vol", 0),
        "turnover": turnover,
        "pre_close": raw.get("last_close", 0),
        "open": raw.get("open", 0),
        "high": raw.get("high", 0),
        "low": raw.get("low", 0),
        "bid_prices": [raw.get(f"bid{i}", 0) for i in range(1, 6)],
        "bid_volumes": [raw.get(f"bid_vol{i}", 0) for i in range(1, 6)],
        "ask_prices": [raw.get(f"ask{i}", 0) for i in range(1, 6)],
        "ask_volumes": [raw.get(f"ask_vol{i}", 0) for i in range(1, 6)],
        "source": "pytdx",
    }


def is_a_share(market, ticker):
    """仅保留当前 ATP 现金交易链路支持的沪深 A 股。"""
    prefixes = {
        0: ("000", "001", "002", "003", "300", "301"),
        1: ("600", "601", "603", "605", "688", "689"),
    }
    return len(ticker) == 6 and ticker.startswith(prefixes.get(market, ()))


def fetch_security_master(api):
    securities = {}
    for market, exchange in ((0, "SZSE"), (1, "SSE")):
        count = int(api.get_security_count(market) or 0)
        for offset in range(0, count, 1000):
            for item in api.get_security_list(market, offset) or []:
                ticker = str(item.get("code", "")).strip()
                if not is_a_share(market, ticker):
                    continue
                security = {
                    "market": market,
                    "ticker": ticker,
                    "exchange": exchange,
                    "name": str(item.get("name", ticker)).strip() or ticker,
                    "lot_size": int(item.get("volunit", 100) or 100),
                }
                securities[(exchange, ticker)] = security
    return sorted(securities.values(), key=lambda item: (item["exchange"], item["ticker"]))


def save_security_master(path, securities):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(securities, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def fetch_quotes(api, securities):
    request = [(security["market"], security["ticker"]) for security in securities]
    result = api.get_security_quotes(request)
    if not result or len(result) != len(securities):
        raise RuntimeError(f"通达信行情返回数量异常: expected={len(securities)}, actual={len(result or [])}")
    return [normalize_quote(raw, security) for raw, security in zip(result, securities)]


def main():
    parser = argparse.ArgumentParser(description="pytdx 本机行情桥")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="获取一次行情并退出")
    args = parser.parse_args()

    config = load_config(args.config)
    api_class = import_tdx_api()
    api = api_class(heartbeat=True, auto_retry=True, raise_exception=True)
    selected = connect(api, config["servers"], config.get("connect_timeout", 2.0))
    print(json.dumps({"event": "tdx_connected", "server": selected}), flush=True)

    security_master = fetch_security_master(api)
    security_by_key = {
        (security["exchange"], security["ticker"]): security
        for security in security_master
    }
    master_path = Path(config.get("security_master_path", "runtime/data/security_master.json"))
    if not master_path.is_absolute():
        master_path = ROOT_DIR / master_path
    save_security_master(master_path, security_master)
    print(json.dumps({
        "event": "security_master_ready",
        "count": len(security_master),
        "path": str(master_path),
    }, ensure_ascii=False), flush=True)

    subscriptions = {}
    for configured in config.get("securities", []):
        key = (configured["exchange"], configured["ticker"])
        security = security_by_key.get(key)
        if security:
            subscriptions[key] = security

    quote_server = None
    try:
        if not args.once:
            listen = config["listen"]
            quote_server = LocalQuoteServer(listen["host"], listen["port"])
            print(json.dumps({"event": "bridge_listening", "listen": listen}), flush=True)

        def subscribe(command):
            if command.get("type") != "subscribe":
                raise ValueError("不支持的行情控制命令")
            key = (str(command.get("exchange", "")).strip().upper(),
                   str(command.get("ticker", "")).strip())
            security = security_by_key.get(key)
            if not security:
                raise ValueError(f"证券主数据中不存在 {key[1]}.{key[0]}")
            subscriptions[key] = security
            print(json.dumps({
                "event": "subscription_added",
                "ticker": security["ticker"],
                "exchange": security["exchange"],
                "name": security["name"],
                "active": len(subscriptions),
            }, ensure_ascii=False), flush=True)

        while True:
            if quote_server:
                quote_server.poll_commands(subscribe)
            securities = list(subscriptions.values())
            batch_size = int(config.get("quote_batch_size", 80))
            for offset in range(0, len(securities), batch_size):
                for quote in fetch_quotes(api, securities[offset:offset + batch_size]):
                    print(json.dumps(quote, ensure_ascii=False), flush=True)
                    if quote_server:
                        quote_server.publish(quote)
            if args.once:
                break
            time.sleep(config.get("poll_interval", 1.0))
    finally:
        if quote_server:
            quote_server.close()
        api.disconnect()


if __name__ == "__main__":
    main()
