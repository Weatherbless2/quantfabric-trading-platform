# 历史 K 线服务

`HistoryDataService` 是分钟 K 线的只读 HTTP 服务。它将 Windows 上的
PostgreSQL 与 WSL 中的 vn.py Qt 前端隔离：桌面端只通过 HTTP 获取已授权的
OHLCV 数据，不直接保存或读取数据库凭据。

```text
VnpyMonitor -> HistoryDataService -> PostgreSQL tdx_init_test.stkprice_1min
       |              |
       |              +-> AuthAdminService/Casbin: market:history
       +-> XServer -> C++ 行情/风控/交易链路
```

支持 `1`、`5`、`15` 分钟周期。表内是分钟数据，5/15 分钟线由服务端按开高低收、
成交量和成交额聚合，实时当前周期则由桌面端从 C++ 行情更新。

## Windows PostgreSQL 主机启动

当前 PostgreSQL 仅监听 Windows 的 `127.0.0.1:5432`，所以服务应在 Windows
主机启动，而不是 WSL。Windows Python 必须能够导入本仓库目录；从仓库根目录打开
Windows PowerShell 后设置本地变量（不要把密码提交到 Git）：

```powershell
$env:QF_HISTORY_DATABASE_URL = 'postgresql://kline_app:<数据库密码>@127.0.0.1:5432/market_data'
$env:QF_HISTORY_SCHEMA = 'tdx_init_test'
$env:QF_HISTORY_TABLE = 'stkprice_1min'
$env:QF_HISTORY_AUTH_URL = 'http://127.0.0.1:18080'
$env:QF_AUTH_INTERNAL_KEY = '<runtime/config/AuthAdmin.env 中的 QF_AUTH_INTERNAL_KEY>'
py -3 -m pip install -r HistoryDataService\requirements.txt
py -3 -m uvicorn HistoryDataService.app:app --host 0.0.0.0 --port 18081
```

Windows Python has its own packages. `fastapi` and `psycopg` must be installed
with the same `py -3` interpreter that starts Uvicorn; the WSL virtual
environments cannot be reused by Windows Python. On the current machine,
`py -3 -m pip show fastapi` is a quick preflight check before starting.

WSL 的 AuthAdmin 已通过 WSL2 localhost forwarding 暴露到 Windows 的
`127.0.0.1:18080`。若 Windows 版本或安全策略关闭了 localhost forwarding，需改为
允许 WSL 网卡访问的地址，并确认防火墙规则；不要开放到公网。

WSL 访问 Windows 服务时，使用 WSL 默认网关。每次重启 WSL 后可用下列命令确认：

```bash
ip -4 route get 1.1.1.1 | awk '{print $7; exit}'
```

如果服务与 `AuthAdminService` 不在同一台机器，`QF_HISTORY_AUTH_URL` 必须指向
授权服务可访问的地址。生产环境应把两个服务部署到受控内网，并使用 TLS/服务身份，
而不是将 PostgreSQL 监听地址直接暴露到局域网。

## WSL 前端配置

服务按上例监听 Windows 的 WSL 内网接口后，在 WSL 使用 Windows 网关
`172.26.112.1` 访问。启动前端前：

```bash
export QF_HISTORY_URL="http://$(ip -4 route | awk '/default/{print $3; exit}'):18081"
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

Windows 防火墙必须只允许来自 WSL 虚拟网卡的 TCP `18081` 入站连接。不要开放
PostgreSQL 的 `5432` 端口。Windows/WSL 网络边界未完成前，前端会继续显示实时 K
线，历史 K 线请求失败只会记录日志，不影响订阅、风控、下单、资金或持仓。

## 验证

服务启动后，在它所在的主机执行：

```powershell
curl http://127.0.0.1:18081/healthz
```

`database: configured` 只表示连接串已经设置。使用有效的 AuthAdmin 会话调用
`/v1/history/minute` 返回实际 `bars` 后，才表示数据库、授权和表映射均已连通。
