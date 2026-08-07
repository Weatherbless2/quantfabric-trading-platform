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
    """单进程广播服务；断开的消费者会在下一次发送时自动移除。"""

    def __init__(self, host, port):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(4)
        self._server.setblocking(False)
        self._clients = []

    def publish(self, quote):
        while True:
            try:
                client, _ = self._server.accept()
                self._clients.append(client)
            except BlockingIOError:
                break

        payload = (json.dumps(quote, ensure_ascii=False) + "\n").encode("utf-8")
        active_clients = []
        for client in self._clients:
            try:
                client.sendall(payload)
                active_clients.append(client)
            except OSError:
                client.close()
        self._clients = active_clients

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

    quote_server = None
    try:
        if not args.once:
            listen = config["listen"]
            quote_server = LocalQuoteServer(listen["host"], listen["port"])
            print(json.dumps({"event": "bridge_listening", "listen": listen}), flush=True)

        while True:
            for quote in fetch_quotes(api, config["securities"]):
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
