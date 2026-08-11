# QuantFabric Trading Platform

QuantFabric 是面向人工交易和后续量化策略接入的 C++ 交易核心。当前交付的是
安全的本地测试链路：C++ Qt 桌面端通过 XServer 接入行情、风控和交易核心；
权限服务使用 Casbin 管理用户、菜单和账户动作。

> 目前只允许使用 `test` 模式验收。公司行情接口、公司柜台 SDK 和真实账户的
> 端到端验收尚未完成，禁止执行 `real-trade`。

## 业务模块

| 模块 | 职责 |
| --- | --- |
| `QtAdmin` | C++ Qt 权限管理端：用户、菜单、角色、账户授权和审计查询。 |
| `QtTrader` | C++ Qt 交易端。当前复用并迁移原 `XMonitor` 页面，通过 HPSocket + PackMessage 直连 XServer。 |
| `AuthAdminService` | 开发登录、短会话、Casbin RBAC/domain 校验、管理 API 与审计。 |
| `XServer` | 客户端协议入口；验证短会话，并对订阅、下单、撤单和账户数据进行服务端二次授权。 |
| `XWatcher` | 核心转发与运行监控，连接网络客户端和共享内存服务。 |
| `XRiskJudge` | 订单风控检查。 |
| `XTrader` | 交易网关；测试模式使用 `TestTrader`，后续替换为 ATP/公司柜台适配器。 |
| `XMarketCenter` | 行情网关；测试模式使用 `TestMarket`，后续替换为 pytdx/公司行情适配器。 |
| `XQuant` | 可选策略引擎，通过共享内存订阅行情和发送交易请求。 |

```text
行情：TestMarket/pytdx/公司行情 -> XMarketCenter -> XWatcher -> XServer -> QtTrader
交易：QtTrader -> XServer -> XWatcher -> XRiskJudge -> XTrader -> 测试柜台/ATP/公司柜台
权限：QtAdmin、QtTrader -> AuthAdminService + Casbin；XServer 对敏感操作再次校验
```

完整边界和后续实现顺序见 [目标架构说明](doc/architecture/TargetArchitecture.md)。

## 本地测试运行

以下命令在仓库根目录执行。首次运行需要 CMake、Qt5、Python 3、SQLite 和
构建工具：

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake curl sqlite3 python3-venv \
    qtbase5-dev qt5-qmake

python3 -m venv .auth-venv
.auth-venv/bin/python -m pip install -r AuthAdminService/requirements.txt

./runtime/prepare.sh
cmake -S . -B build
cmake --build build --target \
    XServer_0.9.0 XWatcher_0.6.0 XRiskJudge_0.9.3 XTrader_0.9.3 \
    XMarketCenter_0.9.3 XQuant_0.1.0 QtAdmin_0.1.0 -j"$(nproc)"
(cd XMonitor && qmake XMonitor.pro -o build/Makefile && make -C build -j"$(nproc)")
```

启动后台测试链路：

```bash
./runtime/start.sh test
curl -fsS http://127.0.0.1:18080/healthz
```

预期健康检查结果：

```json
{"status":"ok","mode":"development"}
```

后台脚本完成后会把服务留在后台运行。另开两个终端启动桌面程序：

```bash
# 终端 2：权限管理端
./build/QtAdmin_0.1.0

# 终端 3：交易端。必须指定日志目录，避免 fmtlog 因默认 ./log 目录不存在而退出。
APP_LOG_PATH="$PWD/runtime/log/" \
    ./XMonitor/build/QtTrader_0.1.0 -f runtime/config/XMonitor.yml
```

开发模式默认登录信息：

```text
权限服务地址：http://127.0.0.1:18080
用户名：admin
密码：123456
```

停止全部后台服务：

```bash
./runtime/stop.sh
```

## 验证

```bash
.auth-venv/bin/python -m unittest -v \
    AuthAdminService.test_service bridges.market.test_pytdx_bridge
git diff --check
git status --short --branch
```

预期 Python 测试共 9 项通过，Git 工作树没有非预期改动。

## 协作说明

根仓库的开发分支是 `feature/qt-trader-session`。当前根仓库保留多个 Git
子模块，团队协作前需要将这些子模块迁移到团队可写的 GitHub 组织或内部 Git
远端，并更新 `.gitmodules`；否则新机器无法可靠还原本地子模块的架构改造提交。
在该迁移完成前，不应直接把功能分支合并到 `main`。
