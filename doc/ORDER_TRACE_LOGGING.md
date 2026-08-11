# QtTrader 订单追踪日志

## 目标

订单追踪从 C++ Qt 客户端开始，到 C++ 交易核心结束。每一笔委托使用同一个
`TraceID`，用于把界面操作、XServer、XWatcher、XRiskJudge、XTrader 与柜台回报
串起来。

```text
QtTrader -> XServer -> XWatcher -> XRiskJudge -> XTrader -> ATP
                                             <- 订单与成交回报 <-
```

QtTrader 只记录用户动作和收到的回报。订单是否受理、是否成交、是否撤单，必须以
XTrader 和柜台回报为准。

## TraceID 规则

报单消息已有 `OrderToken`，不修改 `PackMessage` ABI：

```text
报单 TraceID = QF-资金账号-OrderToken
示例          = QF-ACCOUNT-1800000001
```

撤单消息使用原委托的柜台编号：

```text
撤单 TraceID   = QF-资金账号-REF-OrderRef
ParentTraceID = 原报单 TraceID
```

## 记录位置

| 组件 | 记录内容 |
|---|---|
| QtTrader | 下单或撤单按钮动作、发送失败、最终回报状态 |
| XServer | 会话和账户权限校验、向 XWatcher 的转发、向客户端的回报 |
| XWatcher | 交易消息转发 |
| XRiskJudge | 风控结论、风险编号、耗时 |
| XTrader | 柜台请求、订单与成交回报、错误码 |

C++ 服务使用 FMTLOG。排障时用同一个 TraceID 搜索各服务日志：

```bash
rg 'TraceID=QF-ACCOUNT-1800000001' runtime/log
```

## QtTrader 伪代码

```cpp
const auto token = nextOrderToken();
const auto traceId = makeTraceId(account, token);
logInfo(traceId, "QtTraderSubmit", symbol, price, volume);

xserverSession.sendOrder(order, token);

// UI 状态先显示“已提交”，最终状态由 XServer 回报驱动。
model.updateSubmitted(token);
```

收到回报后，QtTrader 通过 `QAbstractTableModel` 更新委托表，不在 UI 线程中进行
网络读写或风控计算。
