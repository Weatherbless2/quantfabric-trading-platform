# QuantFabric 本地运行说明

以下命令均在仓库根目录执行。`real-trade` 连接 pytdx 和 ATP 测试柜台，并允许
vn.py 人工委托；`real-readonly` 用于只查看行情和账户。

## 1. 首次安装

```bash
git submodule sync --recursive
git submodule update --init --recursive

sudo apt-get update
sudo apt-get install -y build-essential cmake sqlite3 python3-venv qtbase5-dev qt5-qmake
./runtime/setup-bridges.sh
```

`.gitmodules` 已使用 HTTPS；`git submodule sync --recursive` 会清除当前工作区缓存的
旧 SSH 地址，不需要配置 GitHub SSH key。

预期最后输出：

```text
bridge Python environment prepared in .../QuantFabric/.venv
```

## 2. 编译

```bash
cmake -S . -B build
cmake --build build --target \
    XServer_0.9.0 XWatcher_0.6.0 XRiskJudge_0.9.3 XTrader_0.9.3 \
    XMarketCenter_0.9.3 XQuant_0.1.0 \
    TestTrader_0.4.0 TestMarket_0.2.0 \
    ATPTrader_0.1.0 PyTdxMarket_0.1.0 \
    XVnpyBridge_0.1.0 \
    -j"$(nproc)"
```

不要直接构建默认 `all` 目标：仓库中的 CTP 等可选插件需要各自未随仓库提供的
厂商 SDK，例如 `ThostFtdcTraderApi.h`。上面的目标已覆盖本文的模拟和 ATP 链路。

XMonitor 是独立的 Qt/qmake 工程：

```bash
mkdir -p XMonitor/build
qmake XMonitor/XMonitor.pro -o XMonitor/build/Makefile
make -C XMonitor/build -j"$(nproc)"
```

关键产物：

```text
build/XServer_0.9.0
build/XWatcher_0.6.0
build/XRiskJudge_0.9.3
build/XTrader_0.9.3
build/XMarketCenter_0.9.3
build/XQuant_0.1.0
build/libATPTrader_0.1.0.so
build/libPyTdxMarket_0.1.0.so
build/XVnpyBridge_0.1.0
```

## 3. 独立诊断

ATP 只读登录、资金、持仓、委托和成交查询：

```bash
./runtime/atp-diagnose.sh --timeout 12
```

预期包含：

```text
"event": "agw_login"
"event": "customer_login"
"event": "fund"
"event": "position"
"event": "diagnostic_complete", "readonly": true
```

pytdx 单次行情：

```bash
./runtime/pytdx-bridge.sh --once
```

交易时间内预期返回配置中 6 只股票的 `last_price`、`volume`、五档买卖盘。非交易
时间价格或成交量不变化属于正常现象。

## 4. 启动完整链路

准备运行数据库并启动真实行情、真实测试柜台的只读链路：

```bash
./runtime/stop.sh
./runtime/prepare.sh
./runtime/start.sh real-readonly
```

预期输出 9 个 `started`，最后为：

```text
QuantFabric services are running in real-readonly mode. Logs: .../runtime/log
```

核验行情、账户和进程：

```bash
tail -f runtime/log/PyTdxBridge.stdout.log
tail -f runtime/log/ATPBridge.stdout.log
tail -f runtime/log/XMarketCenter.stdout.log
tail -f runtime/log/XQuant.stdout.log
for file in runtime/pids/*.pid; do pid=$(cat "$file"); kill -0 "$pid" && echo "$file running"; done
```

策略日志应持续出现：

```text
Ticker:300007 ... NewOrder:false
```

`NewOrder:false` 是设计结果：`StockReadOnlyStrategy` 只消费行情和账户回报。

## 5. 模拟链路

不连接外部行情和柜台：

```bash
./runtime/stop.sh
./runtime/start.sh test
```

该模式使用 `TestMarket` 和 `TestTrader`，用于验证 QuantFabric 内部的行情、策略、
风控及订单路由。

## 6. 开放交易网关

```bash
./runtime/stop.sh
./runtime/start.sh real-trade
```

此模式向 ATP Python 桥和 C++ 交易插件打开交易开关，同时启动带报单权限的
`XVnpyBridge`。vn.py 发出的请求仍先经过 XServer、XRiskJudge 和 XTrader，风控通过
后才会到达 ATP。现有股票策略不会自动报单，只有界面二次确认后的手工操作会发单。

启动 vn.py 前端：

```bash
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

页面应显示 6 只股票、五档盘口、资金、持仓、限价买卖和撤单功能，顶部状态应为
“交易模式 · C++风控”。

在有图形桌面的终端启动 XMonitor：

```bash
APP_LOG_PATH="$PWD/runtime/log/" \
    ./XMonitor/build/XMonitor_0.9.2 -d -f "$PWD/runtime/config/XMonitor.yml"
```

如需诊断原 XMonitor，可进入 `OrderManager` 后使用 `SendOrder`。普通深圳股票委托
的主要字段为：

```text
Product: ATPTest
Account: 610000071840
Ticker: 300007
Exchange: SZ
OrderType: LIMIT
Direction: Buy 或 Sell
RiskCheck: Check
Engine: TraderOrder
```

价格和数量由下单人确认后填写。`RiskCheck: Check` 会先经过 XRiskJudge，挂单可在
委托表中双击撤单。
XMonitor 使用 `SH`/`SZ`，ATP 桥也兼容内部行情链路使用的 `SSE`/`SZSE`。

不要直接运行厂商原始示例 `AtpTraderOfGuosen(1)/bin/atp_gs_trade_py38.py`，该脚本
启动后会自动委托并撤单。

## 7. 停止

```bash
./runtime/stop.sh
```

该命令停止核心服务、两个 Python 桥和 `XVnpyBridge`，并清理本次使用的共享内存文件。
