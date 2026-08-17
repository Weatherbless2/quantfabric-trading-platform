"""Command line entry point for a read-only ClickHouse backtest."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .engine import BacktestConfig, run_backtest


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantFabric ClickHouse 均线回测")
    parser.add_argument("--symbol", default="300007")
    parser.add_argument("--exchange", default="SZSE", choices=("SSE", "SZSE"))
    parser.add_argument("--start", required=True, help="开始时间，例如 2025-01-01")
    parser.add_argument("--end", required=True, help="结束时间，例如 2025-12-31")
    parser.add_argument("--interval", type=int, default=5, choices=(1, 5, 15, 30, 60))
    parser.add_argument("--fast", type=int, default=10)
    parser.add_argument("--slow", type=int, default=30)
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-duty-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/data/backtest"))
    args = parser.parse_args()
    result = run_backtest(BacktestConfig(
        symbol=args.symbol, exchange=args.exchange,
        start=datetime.fromisoformat(args.start), end=datetime.fromisoformat(args.end),
        interval=args.interval, fast_window=args.fast, slow_window=args.slow,
        capital=args.capital, commission_rate=args.commission_rate,
        stamp_duty_rate=args.stamp_duty_rate, slippage_bps=args.slippage_bps,
    ))
    report, trades = result.write(args.output_dir)
    print(f"数据源: {result.source}\nK线数: {result.bars}\n成交笔数: {len(result.trades)}")
    if not result.bars:
        print("提示: 指定区间没有该证券的历史数据，未执行交易模拟。")
    print(f"期末权益: {result.final_equity:.2f}\n收益率: {result.return_rate:.2%}\n年化收益: {result.annualized_return:.2%}\n"
          f"最大回撤: {result.max_drawdown:.2f}\n夏普比率: {result.sharpe_ratio:.2f}\n胜率: {result.win_rate:.2%}\n"
          f"换手率: {result.turnover:.2%}\n总交易成本: {result.total_cost:.2f}")
    print(f"报告: {report}\n成交明细: {trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
