# QuantFabric vn.py 交易前端

该前端使用 vn.py 4.4.0 的事件引擎、标准数据对象和监控组件。它通过
`quantfabric_native` 原生 Python 扩展连接 XServer，报单及撤单固定经过以下链路：

```text
vn.py Qt -> quantfabric_native -> XServer -> XWatcher -> XRiskJudge -> XTrader -> ATP
```

Python 界面不复制 C++ 风控，也不会绕过 QuantFabric 直接访问 ATP 报单端口。

## 安装

在仓库根目录执行：

```bash
python3 -m venv .vnpy-venv
.vnpy-venv/bin/python -m pip install --upgrade pip
.vnpy-venv/bin/python -m pip install -r VnpyMonitor/requirements.txt
.vnpy-venv/bin/python -m pip install -r AuthAdminService/requirements.txt
```

编译原生扩展需要 Python 开发头文件；Ubuntu/Debian 可执行：

```bash
sudo apt-get install -y python3-dev
```

如中文显示为方框，安装中文字体和 Qt XCB 依赖：

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk libxcb-cursor0
```

## 启动交易模式

```bash
cmake -S . -B build
cmake --build build --target quantfabric_native -j"$(nproc)"
./runtime/stop.sh
./runtime/prepare.sh
./runtime/start.sh real-trade
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

本地开发使用 `admin` / `123456` 向 AuthAdminService 换取短会话。生产环境在网关设置中
填写 Keycloak access token 到“OIDC访问令牌”；桌面密码和令牌均不会写入 XServer 的
PackMessage 登录包。

预期顶部显示“交易模式 · C++风控”和“证券库 5212 只”（数量随行情源主数据变化），
标的选择框支持按代码或名称检索。选择标的或在“证券库”页双击记录后，界面会按需
订阅该证券的实时行情；右侧显示限价、数量、买入和卖出操作。委托提交前会二次确认；
双击活动委托可确认撤单。

## 当前功能

- 启动时从通达信同步的沪深 A 股证券库；实时行情和五档盘口按用户选择订阅
- 左侧全量证券库支持代码/名称检索和双击订阅，顶部下拉框也可滚动选择
- 将实时行情按分钟聚合为 K 线和成交量图，数据从前端启动后开始累积
- ATP 测试账户资金、持仓和委托查询
- 普通股票限价买入、限价卖出
- 委托状态展示和活动委托撤单
- C++ 风控和服务连接状态展示

当前交易范围是 ATP 现金交易支持的沪深 A 股。证券库中的标的仍会受到账户权限、
停牌状态、价格规则、持仓与可用资金，以及 ATP 柜台校验的约束。第一版不支持
市价单、FAK/FOK、融资融券、逆回购、申购和策略编辑；北京交易所、ETF、债券等
品种需补齐各自的合约映射和风控规则后再接入。

当前行情链路只提供实时快照，因此 K 线不伪造启动前的历史数据。要在打开标的时立即
展示历史日线或分钟线，需要公司行情接口提供历史 K 线查询能力，再通过 C++ 行情链路
接入 vn.py 图表。

`real-trade` 会允许人工操作测试柜台。需要仅查看数据时可显式使用
`./runtime/start.sh real-readonly`；C++ 柜台插件会拒绝交易请求。
