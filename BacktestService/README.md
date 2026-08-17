# ClickHouse 回测

回测读取 `tdxdata.stkprice_1min` 的只读分钟数据，使用 vn.py 4.4.0 兼容的独立执行逻辑。它不启动 ATP、不连接 XServer，也不会产生真实委托。

```bash
./runtime/backtest.sh --symbol 300007 --exchange SZSE \
  --start 2026-03-11 --end 2026-08-11 --interval 5 --fast 10 --slow 30
```

成交使用信号产生后的下一根 K 线开盘价，并计入滑点、手续费、卖出印花税和 A 股 100 股一手约束。
可通过 `--commission-rate`、`--stamp-duty-rate`、`--slippage-bps` 调整成本假设；输出包含年化收益、
夏普、换手率、总交易成本以及每根 K 线的权益/回撤曲线的 JSON 汇总和 CSV 成交明细到
`runtime/data/backtest/`，该目录是本地运行产物，不提交 Git。

交易工作台的“策略回测”页通过 `BacktestService` HTTP 接口执行同一套引擎。启动接口服务：

```bash
./runtime/start-backtest-service.sh
```

接口使用当前登录会话的 `market:history` 权限，ClickHouse 凭据只存在服务端；它不会连接 ATP，
也不会发送交易委托。

先确认标的覆盖范围。当前 CK 全库覆盖 `2021-08-16` 到 `2026-08-11`，但不同证券的
首个有效时间不同；区间没有该证券数据时，回测会得到 0 根 K 线并保留空报告，不会补造数据。
回测结果只代表历史撮合假设，实盘前仍需经过已发布的 BusinessAdmin 证券规则、XRiskJudge
和 ATP 柜台回报验证。
