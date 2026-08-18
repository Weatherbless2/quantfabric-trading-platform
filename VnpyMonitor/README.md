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

## ATP 测试柜台启动

```bash
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.vnpy-venv/bin/python"
cmake --build build --target quantfabric_native -j"$(nproc)"
./runtime/prepare.sh
./runtime/start.sh
./runtime/start-history-data.sh
./runtime/start-backtest-service.sh
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

默认是手工交易。需要显式启用共享均线策略时使用：

```bash
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app \
  --strategy ma-cross --strategy-volume 100 --strategy-fast 10 --strategy-slow 30
```

策略只在上一分钟 Bar 完成后计算，历史分钟 Bar 只用于预热，不会产生历史委托；
连接断开时自动暂停发单。每个策略信号仍通过 vn.py 标准 `OrderRequest` 进入
`XServer -> XRiskJudge -> XTrader -> ATP`，不会绕过现有权限、发布配置和风控。
不传 `--strategy ma-cross` 时，工作台保持手工买卖模式。

## 策略回测页

启动回测服务后，工作台底部的“策略回测”页可以选择证券、交易所、日期范围、K 线周期、
快慢均线和初始资金，直接展示收益率、最大回撤、夏普比率、交易成本及成交明细。页面通过
`BacktestService` 请求历史数据，不直连 ClickHouse，也不会触发 ATP 委托。服务地址为
`http://127.0.0.1:18082`。回测结果还包含累计收益和回撤时间曲线，用于观察策略在整个
区间内的权益变化。

## 历史 K 线

工作台的 `1`、`5`、`15`、`30`、`60 分钟` 与 `日 K` 周期按钮会优先从
`HistoryDataService` 加载 ClickHouse 中的分钟 K 线，再用本次桌面会话的实时行情
覆盖当前周期。历史查询和实时订阅分别需要 Casbin 的 `market:history` 与
`market:subscribe` 权限；两者都由服务端校验，前端不直连数据库。

```text
vn.py Qt -> HistoryDataService -> ClickHouse 分钟 K 线
vn.py Qt -> quantfabric_native -> XServer -> C++ 实时行情、风控、交易
```

历史服务的本机启动和数据源配置见
[`HistoryDataService/README.md`](../HistoryDataService/README.md)。在服务未部署时，
界面仍可使用实时行情和交易；K 线仅从前端启动后开始累积。

本地开发使用 `admin` / `123456` 向 AuthAdminService 换取短会话。桌面密码不会写入
XServer 的 PackMessage 登录包。默认产品和账户为 `ATPTest / 610000071840`。
实时行情由 pytdx 适配器进入 XMarketCenter；资金、持仓、委托和成交来自
`ATPTrader -> ATP SDK -> AGW`。报单和撤单不会绕过后台发布规则或 C++ 风控。

## 权限后台到交易工作台的操作链路

`QtAdmin` 和交易工作台不是两个相互嵌套的页面。它们通过
`AuthAdminService` 协作，关键动作仍由 XServer 二次校验：

```text
QtAdmin 创建用户/策略/账户授权
    -> AuthAdminService + Casbin
    -> VnpyMonitor 用该用户登录取得短会话
    -> XServer 在订阅、读账户、下单、撤单时再次请求 Casbin
```

1. 启动 `./build/QtAdmin_0.1.0`，以 `admin` / `123456` 登录。
2. 在“用户”中新建操作员；用户名为 `alice` 时，Casbin 主体写作 `user:alice`。
3. 在“策略”中新增该用户的行情规则，例如：域 `desk:cn_equity`、资源
   `market/SZSE/instrument/300007`、动作 `market:subscribe`。
4. 在“账户授权”中为 `user:alice`、账户 `610000071840` 依次授予 `account:read`、
   `order:read`、`order:create`、`order:cancel`。
5. 在新终端以该操作员启动工作台：

```bash
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app \
  --user alice --password '用户创建时设置的密码' \
  --account 610000071840 --product ATPTest
```

未配置行情策略时订阅会被拒绝；未配置 `order:create` 时下单会被拒绝。结果均会出现在
QtAdmin 的“审计”页和 XServer 日志中。已运行的桌面会话保留其短会话，权限变更后应
关闭并重新登录工作台，以取得新的会话并避免将旧界面状态误认为新授权结果。

### 权限规则的实际效果

| Casbin 资源与动作 | 获得后可以做什么 | 未获得时的表现 |
| --- | --- | --- |
| `market/SZSE/instrument/000014` + `market:subscribe` | 订阅指定股票的实时行情和五档盘口 | XServer 拒绝订阅，当前标的不会收到报价，买卖按钮保持禁用 |
| `account/610000071840` + `account:read` | 查看该账户的资金和持仓推送 | 看不到该账户的资金、持仓回报 |
| `account/610000071840` + `order:read` | 查看该账户的委托和成交状态 | 看不到该账户的委托状态回报 |
| `account/610000071840` + `order:create` | 发起买入或卖出委托 | XServer 拒绝委托，审计页记录拒绝原因 |
| `account/610000071840` + `order:cancel` | 撤销仍处于可撤状态的委托 | XServer 拒绝撤单，审计页记录拒绝原因 |

本地 `admin` 是开发全权限账户；普通操作员建议只授予其负责账户和标的的最小权限。
ATP 测试柜台决定订单是否成交以及是否可撤，界面只对活动委托开放撤单。

`--user`、`--password`、`--account`、`--product`、`--auth-url` 也可分别使用
`QF_VNPY_USER`、`QF_VNPY_PASSWORD`、`QF_VNPY_ACCOUNT`、`QF_VNPY_PRODUCT`、
`QF_VNPY_AUTH_URL` 环境变量设置。

## 工作台页面

启动后默认进入“总览”。左侧菜单通过 `QStackedWidget` 切换以下独立页面；页面首次打开时才创建重量级图表和监控表格，同一页面重复切换会复用实例：

| 页面 | 内容 |
| --- | --- |
| 总览 | 账户权益、可用资金、持仓数量、最近委托/成交和当前证券摘要 |
| 行情中心 | 全量证券搜索、按选中标的订阅实时行情、K 线、分时、五档和 Tick |
| 交易下单 | 当前标的、限价和数量、预估金额、可用资金、可卖数量及确认下单 |
| 账户持仓 | vn.py 资金和持仓监控器 |
| 委托成交 | 当前委托、当日成交和活动委托确认撤单；历史查询待服务接入 |
| 策略回测 | ClickHouse 历史数据回测、收益/回撤曲线和成交明细 |
| 策略管理 | 已启用策略的真实状态；未接入策略托管时显示空状态 |
| 系统设置 | 当前账户、产品、认证、历史和回测服务配置（只读） |

页面拆分只改变 Qt 控件组织方式。行情、下单、风控、ATP 和回测服务的接口及事件链路保持不变。

## 当前功能

- 可加载 5,212 只沪深 A 股证券库；实时行情和五档盘口按用户选择订阅
- 左侧全量证券库支持代码/名称检索，单击证券即订阅并切换当前行情、盘口、K 线和委托标的
- 将实时行情按分钟聚合为 K 线和成交量图，数据从前端启动后开始累积
- XServer 推送的资金、持仓、委托和成交；成交以柜台累计成交量增量生成，恢复查询不会重复展示
- 普通股票限价买入、限价卖出
- 委托状态展示和活动委托撤单
- 首屏只展示当前标的的核心行情和五档盘口；运行日志保留在 `runtime/log/`，不占用交易界面
- 交易会话与当前标的行情就绪状态展示
- 本机持久化订单令牌，桌面重启后不会与 ATP 桥的幂等日志复用旧 `OrderToken`

当前交易范围规划为 ATP 现金交易支持的沪深 A 股。证券库中的标的仍会受到账户权限、
停牌状态、价格规则、持仓与可用资金，以及 ATP 柜台校验的约束。第一版不支持
市价单、FAK/FOK、融资融券、逆回购、申购和策略编辑；北京交易所、ETF、债券等
品种需补齐各自的合约映射和风控规则后再接入。

当前行情链路只提供实时快照，因此 K 线不伪造启动前的历史数据。要在打开标的时立即
展示历史日线或分钟线，需要启动 `HistoryDataService` 并配置其只读数据源。未来公司行情
接口提供历史 K 线后，在该服务的数据源适配层接入，不改变 vn.py 图表和 C++ 交易链路。

当前唯一标准启动模式为 ATP 测试柜台全功能模式：查询、限价买卖和撤单均已开放，
同时继续受后台发布配置、Casbin、XServer 和 XRiskJudge 约束。
