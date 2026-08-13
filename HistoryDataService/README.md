# 历史 K 线服务

`HistoryDataService` 是 vn.py 工作台使用的只读分钟 K 线 HTTP 服务。默认从服务器
`172.16.20.10:8123` 的 ClickHouse 库 `tdxdata.stkprice_1min` 查询全量数据；桌面端不
直接连接数据库，也不保存数据库凭据。

```text
VnpyMonitor -> HistoryDataService -> ClickHouse tdxdata.stkprice_1min
       |              |
       |              +-> AuthAdminService/Casbin: market:history
       +-> XServer -> C++ 行情/风控/交易链路
```

支持 `1`、`5`、`15`、`30`、`60` 分钟与日 K 周期。数据表只需存储一分钟数据，服务端按开、高、低、收、成交量和
成交额聚合成对应 K 线；日 K 按交易日聚合，不会把不同日期的分钟行情混合。当前周期实时更新仍来自 C++ 实时行情链路。

## 数据源边界与容错

`/v1/history/minute` 是工作台唯一依赖的历史数据契约：输入证券、交易所和周期，输出 OHLCV
K 线。ClickHouse 只是该契约当前的默认实现，不是 vn.py、XServer、风控或柜台的依赖：

```text
公司实时行情 SDK -> XMarketCenter 公司插件 -> XWatcher -> XServer -> vn.py
ClickHouse / 公司历史接口 -> HistoryDataService -> OHLCV HTTP -> vn.py K 线
vn.py -> XServer -> XRiskJudge -> XTrader -> 柜台
```

因此以后接入公司行情时，实时部分替换或新增 `XMarketCenter` 插件；历史部分只新增
`HistoryDataService` 数据源适配器或改本地映射。二者均不应修改下单、风控、订单协议或柜台
适配。ClickHouse 短暂不可用时，服务仅向已通过 Casbin 校验的请求返回最多 60 秒的缓存，并
标记 `stale: true`；缓存不可用于下单定价。缓存没有命中时只影响历史图表，不影响实时行情、
风控或交易服务。

当前默认映射沿用 TDX 编码：沪深都查 `market=S`，证券编码为 `SZSE:000001`。在确认服务器
实际编码后，可只修改本机配置：

```bash
# 例：服务器以 H/Z 区分沪深，并且 stkcode 只保存六码代码。
QF_HISTORY_MARKET_CODES='SSE=H,SZSE=Z'
QF_HISTORY_SYMBOL_TEMPLATE='{symbol}'
```

## 本机启动

历史服务是交易运行时的可选进程。它与 `runtime/start.sh test` 分开启动，避免数据库权限、
网络或维护窗口阻断本地模拟交易链路。

先在仓库根目录建立本机私密配置。模板不含密码，真实配置已被 Git 忽略：

```bash
cp runtime/config/HistoryData.env.example runtime/config/HistoryData.env
chmod 600 runtime/config/HistoryData.env
```

编辑 `runtime/config/HistoryData.env`，填入 ClickHouse 的只读账号和密码：

```text
QF_HISTORY_BACKEND=clickhouse
QF_HISTORY_CLICKHOUSE_URL=http://172.16.20.10:8123
QF_HISTORY_CLICKHOUSE_DATABASE=tdxdata
QF_HISTORY_TABLE=stkprice_1min
QF_HISTORY_CLICKHOUSE_USERNAME=<只读账号>
QF_HISTORY_CLICKHOUSE_PASSWORD=<只读密码>
```

随后运行：

```bash
.auth-venv/bin/python -m pip install -r HistoryDataService/requirements.txt
./runtime/prepare.sh
./runtime/start-history-data.sh
curl http://127.0.0.1:18081/healthz
curl http://127.0.0.1:18081/readyz
```

预期 `/healthz` 返回 `backend: clickhouse` 和 `database: configured`；`/readyz` 返回
`status: ready` 才代表 ClickHouse 可查询。服务只绑定 `127.0.0.1`，不向局域网暴露数据库
代理或密码。

`BusinessAdminService` 的“行情库状态”页面会使用受内部服务密钥保护的汇总接口显示行数和
时间范围；它不会保存或使用 ClickHouse 凭据。要在后台页面看到该状态，先启动历史服务，再
启动或重启后台服务。

启动 vn.py 工作台时指向该服务：

```bash
export QF_HISTORY_URL=http://127.0.0.1:18081
DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

停止历史服务：

```bash
./runtime/stop-history-data.sh
```

## 连通性与数据验证

ClickHouse 需要有效的只读凭据。没有凭据时，服务会健康启动但 `/readyz` 和历史查询会返回
`503`；这是预期的 fail-closed 行为，不能据此宣称全量历史 K 线已接入。

取得账号后，先执行只读抽样，确认字段类型、市场编码和证券编码：

```bash
curl --user "$QF_HISTORY_CLICKHOUSE_USERNAME:$QF_HISTORY_CLICKHOUSE_PASSWORD" \
  --data-binary 'DESCRIBE TABLE tdxdata.stkprice_1min FORMAT JSONEachRow' \
  http://172.16.20.10:8123/

curl --user "$QF_HISTORY_CLICKHOUSE_USERNAME:$QF_HISTORY_CLICKHOUSE_PASSWORD" \
  --data-binary 'SELECT market, stkcode, trdtime, open, high, low, close, vol, amt
                 FROM tdxdata.stkprice_1min ORDER BY trdtime DESC LIMIT 20 FORMAT JSONEachRow' \
  http://172.16.20.10:8123/
```

再使用已登录的桌面会话调用 `/v1/history/minute`，核对返回 K 线的根数、首尾时间和
OHLCV 数值。只有实际 `bars` 返回后，才表示鉴权、源编码和全量历史数据已经一起验收。

## PostgreSQL 迁移回退

原 PostgreSQL 实现仍可用于历史环境迁移，但必须显式启用，避免误以为正在读 ClickHouse：

```text
QF_HISTORY_BACKEND=postgres
QF_HISTORY_DATABASE_URL=postgresql://<只读账号>:<密码>@<主机>:5432/<数据库>
QF_HISTORY_SCHEMA=tdx_init_test
QF_HISTORY_TABLE=stkprice_1min
```

该回退路径与 ClickHouse 保持同一 OHLCV HTTP 契约，不能让 vn.py 直接连接任一数据库。
