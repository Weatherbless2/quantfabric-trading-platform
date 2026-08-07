# QuantFabric vn.py 只读前端

该前端使用 vn.py 4.4.0 的事件引擎、主引擎、标准数据对象和监控组件，连接现有
QuantFabric 本机桥接层。它只发送资金、持仓、委托和成交查询，不提供报单或撤单
实现；C++ 风控、交易路由和行情中心仍是业务核心。

## 安装

在仓库根目录执行：

```bash
python3 -m venv .vnpy-venv
.vnpy-venv/bin/python -m pip install --upgrade pip
.vnpy-venv/bin/python -m pip install -r VnpyMonitor/requirements.txt
```

## 启动

先启动 QuantFabric 只读链路，再打开前端：

```bash
./runtime/stop.sh
./runtime/prepare.sh
./runtime/start.sh real-readonly
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

页面顶部应显示行情桥和 ATP 桥在线，并持续更新 `300007` 行情、五档盘口、ATP
测试资金及持仓。`C++中间层` 状态来自 `127.0.0.1:8000` 的实时端口检测。

当前页面始终显示“只读模式 · 禁止下单”。公司行情和交易 SDK 到位后，应替换桥接
实现或增加版本化的 C++ UI Adapter，不应在 Python UI 中复制风控和订单状态机。
