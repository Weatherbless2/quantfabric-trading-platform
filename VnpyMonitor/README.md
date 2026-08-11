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

## 安全 test 启动

```bash
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.vnpy-venv/bin/python"
cmake --build build --target quantfabric_native -j"$(nproc)"
./runtime/prepare.sh
./runtime/start.sh test
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

本地开发使用 `admin` / `123456` 向 AuthAdminService 换取短会话。桌面密码不会写入
XServer 的 PackMessage 登录包。默认账户 `188795` 与 `TestTrader` 测试链路对应。

选择证券库中的任意沪深 A 股后，工作台会发送订阅请求；测试行情网关仅为已订阅标的
按需生成模拟五档行情。收到该标的首笔报价前，买卖按钮保持禁用。`TestTrader` 对通过
风控的委托产生模拟全成、资金和持仓回报。它不连接 pytdx、ATP 或真实柜台，不能用于
真实交易。

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
4. 在“账户授权”中为 `user:alice`、账户 `188795` 依次授予 `account:read`、
   `order:read`、`order:create`、`order:cancel`。
5. 在新终端以该操作员启动工作台：

```bash
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app \
  --user alice --password '用户创建时设置的密码' --account 188795
```

未配置行情策略时订阅会被拒绝；未配置 `order:create` 时下单会被拒绝。结果均会出现在
QtAdmin 的“审计”页和 XServer 日志中。已运行的桌面会话保留其短会话，权限变更后应
关闭并重新登录工作台，以取得新的会话并避免将旧界面状态误认为新授权结果。

### 权限规则的实际效果

| Casbin 资源与动作 | 获得后可以做什么 | 未获得时的表现 |
| --- | --- | --- |
| `market/SZSE/instrument/000014` + `market:subscribe` | 订阅指定股票的实时行情和五档盘口 | XServer 拒绝订阅，当前标的不会收到报价，买卖按钮保持禁用 |
| `account/188795` + `account:read` | 查看该账户的资金和持仓推送 | 看不到该账户的资金、持仓回报 |
| `account/188795` + `order:read` | 查看该账户的委托和成交状态 | 看不到该账户的委托状态回报 |
| `account/188795` + `order:create` | 发起买入或卖出委托 | XServer 拒绝委托，审计页记录拒绝原因 |
| `account/188795` + `order:cancel` | 撤销仍处于可撤状态的委托 | XServer 拒绝撤单，审计页记录拒绝原因 |

本地 `admin` 是开发全权限账户；普通操作员建议只授予其负责账户和标的的最小权限。测试
订单会立即全成，因此测试模式下不会出现可撤委托；这不是 `order:cancel` 规则失效。

`--user`、`--password`、`--account`、`--auth-url` 也可分别使用
`QF_VNPY_USER`、`QF_VNPY_PASSWORD`、`QF_VNPY_ACCOUNT`、`QF_VNPY_AUTH_URL`
环境变量设置。

## 当前功能

- 可加载 5,212 只沪深 A 股证券库；实时行情和五档盘口按用户选择订阅
- 左侧全量证券库支持代码/名称检索和双击订阅，顶部下拉框也可滚动选择
- 将实时行情按分钟聚合为 K 线和成交量图，数据从前端启动后开始累积
- XServer 推送的资金、持仓和委托查询
- 普通股票限价买入、限价卖出
- 委托状态展示和活动委托撤单
- 交易会话与当前标的行情就绪状态展示

当前交易范围规划为 ATP 现金交易支持的沪深 A 股。证券库中的标的仍会受到账户权限、
停牌状态、价格规则、持仓与可用资金，以及 ATP 柜台校验的约束。第一版不支持
市价单、FAK/FOK、融资融券、逆回购、申购和策略编辑；北京交易所、ETF、债券等
品种需补齐各自的合约映射和风控规则后再接入。

当前行情链路只提供实时快照，因此 K 线不伪造启动前的历史数据。要在打开标的时立即
展示历史日线或分钟线，需要公司行情接口提供历史 K 线查询能力，再通过 C++ 行情链路
接入 vn.py 图表。

`real-readonly` 会连接行情和柜台只读查询，但 C++ 柜台插件拒绝交易请求。
`real-trade` 会开放人工委托，必须在公司行情、柜台配置、账户授权和端到端风控
验收均通过后，由人工明确执行；当前不要使用该模式。
