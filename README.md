# QuantFabric Trading Platform

基于 QuantFabric 的 C++ Qt 量化交易平台学习与协作仓库。

当前目标是构建一个本地部署的桌面交易平台：C++ Qt 交易端直接连接
QuantFabric C++ 交易核心；Python 仅用于权限服务和外部行情适配，不作为桌面端和
交易核心之间的中间层。

> 当前仓库用于学习、开发和 ATP 模拟/测试柜台验证。未完成风控、账户授权和柜台
> 配置审核前，禁止用于真实交易。

## 当前进度

- 已有：QuantFabric C++ 核心、XServer、XWatcher、XRiskJudge、XTrader、
  XMarketCenter、AuthAdminService、Casbin 权限校验。
- 已确定：C++ Qt 客户端直接通过 HPSocket + PackMessage 连接 XServer。
- 规划中：`QtTrader`（交易端）与 `QtAdmin`（管理端）两个 C++ Qt 子项目。
- 不在当前范围：Redis、Keycloak、复杂审批流、多租户，以及桌面端 Python/C++
  中间层。

## 目标架构

```mermaid
flowchart LR
    QtAdmin["QtAdmin<br/>C++ Qt 管理端"] -->|HTTP 管理 API| Auth["AuthAdminService<br/>登录、短会话、Casbin"]
    QtTrader["QtTrader<br/>C++ Qt 交易端"] -->|HTTP 登录| Auth
    QtTrader <-->|HPSocket + PackMessage| XServer["XServer<br/>会话与账户权限"]
    XServer -->|服务端权限校验| Auth
    PyTdx["pytdx 行情适配"] --> Market["XMarketCenter"]
    Market --> Watcher["XWatcher"]
    XServer -->|下单、撤单| Watcher
    Watcher --> Risk["XRiskJudge"] --> Trader["XTrader"]
    Trader <--> ATP["ATP 模拟/测试柜台"]
    Trader -->|订单、成交、资金、持仓回报| Watcher
    Watcher --> XServer
```

完整职责、数据流和实现顺序见
[目标架构文档](doc/architecture/TargetArchitecture.md)。

## 首次构建

以下命令在 WSL Ubuntu 的仓库根目录执行：

```bash
git submodule update --init --recursive

sudo apt-get update
sudo apt-get install -y build-essential cmake curl sqlite3 python3-venv \
    qtbase5-dev qt5-qmake

python3 -m venv .auth-venv
.auth-venv/bin/python -m pip install -r AuthAdminService/requirements.txt

./runtime/setup-bridges.sh
./runtime/prepare.sh

cmake -S . -B build
cmake --build build --target \
    XServer_0.9.0 XWatcher_0.4.0 XRiskJudge_0.9.3 XTrader_0.9.3 \
    XMarketCenter_0.9.3 XQuant_0.1.0 \
    -j"$(nproc)"
```

## 本地测试运行

先启动安全的本地测试链路：

```bash
./runtime/start.sh test
```

停止服务：

```bash
./runtime/stop.sh
```

`runtime/prepare.sh` 生成的数据库、日志、PID 和 `AuthAdmin.env` 都是本机运行状态，
不能提交到 Git。

更完整的运行说明见 [runtime/README.md](runtime/README.md)。

## 团队协作

- `main`：稳定架构基线，只通过 Pull Request 合并。
- `feature/...`：每个功能独立开发，例如 `feature/qt-admin`、
  `feature/qt-trader-session`。
- 提交前只暂存明确文件，禁止将本机 SDK、账户配置、数据库、日志或构建产物上传。
- 每个 Pull Request 应包含功能说明、验证方式和不包含的内容，并由 mentor 审核。

## 目录概览

| 目录 | 作用 |
|---|---|
| `AuthAdminService/` | Python 权限服务：登录、短会话、菜单与账户授权、Casbin |
| `XServer/` | C++ 客户端协议入口、会话和账户动作校验 |
| `XWatcher/` | C++ 核心消息转发与监控 |
| `XRiskJudge/` | C++ 交易风控 |
| `XTrader/` | C++ 柜台交易接入 |
| `XMarketCenter/` | C++ 行情接入与分发 |
| `runtime/` | 本地准备、启动、停止脚本与示例配置 |
| `doc/architecture/` | 当前和目标架构文档 |
