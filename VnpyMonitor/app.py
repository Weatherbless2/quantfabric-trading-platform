#!/usr/bin/env python3
"""启动 QuantFabric vn.py 交易工作台。"""

from __future__ import annotations

import argparse
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
    main_engine.connect(QuantFabricGateway.default_setting.copy(), GATEWAY_NAME)

    if args.screenshot:
        def capture() -> None:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            screen = qapp.primaryScreen()
            if screen:
                screen.grabWindow(window.winId()).save(str(args.screenshot))
            window.close()
            qapp.quit()

        QtCore.QTimer.singleShot(max(args.screenshot_delay, 1000), capture)

    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
