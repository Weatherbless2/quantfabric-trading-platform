# QuantFabric vn.py 交易前端

该前端使用 vn.py 4.4.0 的事件引擎、标准数据对象和监控组件。行情和账户回报来自
QuantFabric 本机桥，报单及撤单固定经过以下链路：

```text
vn.py -> XVnpyBridge -> XServer -> XWatcher -> XRiskJudge -> XTrader -> ATP
```

Python 界面不复制 C++ 风控，也不会绕过 QuantFabric 直接访问 ATP 报单端口。

## 安装

在仓库根目录执行：

```bash
python3 -m venv .vnpy-venv
.vnpy-venv/bin/python -m pip install --upgrade pip
.vnpy-venv/bin/python -m pip install -r VnpyMonitor/requirements.txt
```

如中文显示为方框，安装中文字体和 Qt XCB 依赖：

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk libxcb-cursor0
```

## 启动交易模式

```bash
cmake -S . -B build
cmake --build build --target XVnpyBridge_0.1.0 -j"$(nproc)"
./runtime/stop.sh
./runtime/prepare.sh
./runtime/start.sh real-trade
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

预期顶部显示“交易模式 · C++风控”，标的选择框出现 6 只股票，右侧显示限价、
数量、买入和卖出操作。委托提交前会二次确认；双击活动委托可确认撤单。

## 当前功能

- 6 只沪深股票实时行情与五档盘口
- ATP 测试账户资金、持仓和委托查询
- 普通股票限价买入、限价卖出
- 委托状态展示和活动委托撤单
- C++ 风控和服务连接状态展示

第一版不支持市价单、FAK/FOK、融资融券、逆回购、申购和策略编辑。

`real-trade` 会允许人工操作测试柜台。需要仅查看数据时可显式使用
`./runtime/start.sh real-readonly`，此时页面仍正常显示，但买卖按钮保持禁用。
