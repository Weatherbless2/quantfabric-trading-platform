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
from VnpyMonitor.strategy import VnpyStrategyRunner
from VnpyMonitor.ui import STYLE, WorkbenchWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantFabric vn.py 交易工作台")
    parser.add_argument("--screenshot", type=Path, help="启动后保存界面截图并退出")
    parser.add_argument("--screenshot-delay", type=int, default=5000, help="截图等待毫秒数")
    parser.add_argument("--user", default=os.getenv("QF_VNPY_USER", "admin"),
                        help="AuthAdminService 操作员用户名")
    parser.add_argument("--password", default=os.getenv("QF_VNPY_PASSWORD", "123456"),
                        help="AuthAdminService 操作员密码")
    parser.add_argument("--account", default=os.getenv("QF_VNPY_ACCOUNT", "610000071840"),
                        help="本次会话申请使用的资金账户")
    parser.add_argument("--product", default=os.getenv("QF_VNPY_PRODUCT", "ATPTest"),
                        help="交易产品标识；必须与后台已发布配置和 ATPTrader 配置一致")
    parser.add_argument("--auth-url", default=os.getenv("QF_VNPY_AUTH_URL", "http://127.0.0.1:18080"),
                        help="AuthAdminService 地址")
    parser.add_argument("--history-url", default=os.getenv("QF_HISTORY_URL", ""),
                        help="历史行情服务地址；未设置时只使用实时 K 线")
    parser.add_argument("--backtest-url", default=os.getenv("QF_BACKTEST_URL", "http://127.0.0.1:18082"),
                        help="回测服务地址；未启动服务时回测页仅显示不可用状态")
    parser.add_argument("--strategy", choices=("manual", "ma-cross"),
                        default=os.getenv("QF_STRATEGY", "manual"),
                        help="交易模式；默认手工，显式选择 ma-cross 才允许策略发单")
    parser.add_argument("--strategy-volume", type=int,
                        default=int(os.getenv("QF_STRATEGY_VOLUME", "100")),
                        help="均线策略每次委托股数")
    parser.add_argument("--strategy-fast", type=int,
                        default=int(os.getenv("QF_STRATEGY_FAST", "10")),
                        help="均线策略快线窗口")
    parser.add_argument("--strategy-slow", type=int,
                        default=int(os.getenv("QF_STRATEGY_SLOW", "30")),
                        help="均线策略慢线窗口")
    args = parser.parse_args()

    strategy_runner = None
    if args.strategy == "ma-cross":
        try:
            strategy_runner = VnpyStrategyRunner(
                None, volume=args.strategy_volume,
                fast_window=args.strategy_fast, slow_window=args.strategy_slow,
            )
        except ValueError as exc:
            parser.error(str(exc))

    qapp = create_qapp("QuantFabric vn.py")
    # Explicitly select a CJK font so labels do not become replacement boxes.
    qapp.setFont(QtGui.QFont("Noto Sans CJK SC", 10))
    qapp.setStyleSheet(STYLE)
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(QuantFabricGateway)

    if strategy_runner:
        strategy_runner.main_engine = main_engine
    window = WorkbenchWindow(main_engine, event_engine, strategy_runner)
    window.show()
    # QtAdmin 创建的用户在这里成为实际交易会话的身份；XServer 会以短会话而非
    # 本地用户表验证该身份，并在订阅、下单和撤单时再次调用 Casbin。
    connection_setting = QuantFabricGateway.default_setting.copy()
    connection_setting.update({
        "用户": args.user,
        "密码": args.password,
        "资金账号": args.account,
        "交易产品": args.product,
        "认证服务地址": args.auth_url,
        "历史行情地址": args.history_url,
        "回测服务地址": args.backtest_url,
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
