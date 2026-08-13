# ClickHouse 回测

回测读取 `tdxdata.stkprice_1min` 的只读分钟数据，使用 vn.py 4.4.0 兼容的独立执行逻辑。它不启动 ATP、不连接 XServer，也不会产生真实委托。

```bash
./runtime/backtest.sh --symbol 300007 --exchange SZSE \
  --start 2026-03-11 --end 2026-08-11 --interval 5 --fast 10 --slow 30
```

成交使用信号产生后的下一根 K 线开盘价，并计入滑点、手续费和 A 股 100 股一手约束。输出 JSON 汇总和 CSV 成交明细到 `runtime/data/backtest/`，该目录是本地运行产物，不提交 Git。

先确认标的覆盖范围。当前 CK 全库覆盖 `2021-08-16` 到 `2026-08-11`，但不同证券的
首个有效时间不同；区间没有该证券数据时，回测会得到 0 根 K 线并保留空报告，不会补造数据。
回测结果只代表历史撮合假设，实盘前仍需经过已发布的 BusinessAdmin 证券规则、XRiskJudge
和 ATP 柜台回报验证。
