#!/usr/bin/env python3
"""启动 QuantFabric vn.py 交易工作台。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtCore, QtGui, create_qapp

from VnpyMonitor.gateway import GATEWAY_NAME, QuantFabricGateway
from VnpyMonitor.ui import STYLE, WorkbenchWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantFabric vn.py 交易工作台")
    parser.add_argument("--screenshot", type=Path, help="启动后保存界面截图并退出")
    parser.add_argument("--screenshot-delay", type=int, default=5000, help="截图等待毫秒数")
    parser.add_argument("--user", default=os.getenv("QF_VNPY_USER", "admin"),
                        help="AuthAdminService 操作员用户名")
    parser.add_argument("--password", default=os.getenv("QF_VNPY_PASSWORD", "123456"),
                        help="AuthAdminService 操作员密码")
    parser.add_argument("--account", default=os.getenv("QF_VNPY_ACCOUNT", "188795"),
                        help="本次会话申请使用的资金账户")
    parser.add_argument("--auth-url", default=os.getenv("QF_VNPY_AUTH_URL", "http://127.0.0.1:18080"),
                        help="AuthAdminService 地址")
    args = parser.parse_args()

    qapp = create_qapp("QuantFabric vn.py")
    # Explicitly select a CJK font so labels do not become replacement boxes.
    qapp.setFont(QtGui.QFont("Noto Sans CJK SC", 10))
    qapp.setStyleSheet(STYLE)
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(QuantFabricGateway)

    window = WorkbenchWindow(main_engine, event_engine)
    window.show()
    # QtAdmin 创建的用户在这里成为实际交易会话的身份；XServer 会以短会话而非
    # 本地用户表验证该身份，并在订阅、下单和撤单时再次调用 Casbin。
    connection_setting = QuantFabricGateway.default_setting.copy()
    connection_setting.update({
        "用户": args.user,
        "密码": args.password,
        "资金账号": args.account,
        "认证服务地址": args.auth_url,
    })
    main_engine.connect(connection_setting, GATEWAY_NAME)
    window.subscribe_selected()

    screenshot_saved = not args.screenshot
    if args.screenshot:
        def capture() -> None:
            nonlocal screenshot_saved
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            # QWidget.grab works for an X11 desktop and Qt's headless test
            # platform, while QScreen.grabWindow may silently return no image.
            screenshot_saved = window.grab().save(str(args.screenshot))
            if not screenshot_saved:
                print(f"截图保存失败：{args.screenshot}", file=sys.stderr)
            window.close()
            qapp.quit()

        QtCore.QTimer.singleShot(max(args.screenshot_delay, 1000), capture)

    exit_code = qapp.exec()
    return exit_code if screenshot_saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
