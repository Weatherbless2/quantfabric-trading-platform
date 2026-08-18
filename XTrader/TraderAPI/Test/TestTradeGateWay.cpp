#include "TestTradeGateWay.h"
#include "XPluginEngine.hpp"

CreateObjectFunc(TestTradeGateWay);

TestTradeGateWay::TestTradeGateWay()
{
    m_ConnectedStatus = Message::ELoginStatus::ELOGIN_PREPARED;
}

TestTradeGateWay::~TestTradeGateWay()
{
    DestroyTraderAPI();
}

void TestTradeGateWay::LoadAPIConfig()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} LoadAPIConfig {}", m_XTraderConfig.Account, m_XTraderConfig.TraderAPIConfig);
}

void TestTradeGateWay::GetCommitID(std::string& CommitID, std::string& UtilsCommitID)
{
    CommitID = SO_COMMITID;
    UtilsCommitID = SO_UTILS_COMMITID;
}
void TestTradeGateWay::GetAPIVersion(std::string& APIVersion)
{
    APIVersion = API_VERSION;
}

void TestTradeGateWay::CreateTraderAPI()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} CreateTraderAPI", m_XTraderConfig.Account);
}

void TestTradeGateWay::DestroyTraderAPI()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} DestroyTraderAPI", m_XTraderConfig.Account);
}

void TestTradeGateWay::ReqUserLogin()
{
    m_ConnectedStatus = Message::ELoginStatus::ELOGIN_SUCCESSED;
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqUserLogin", m_XTraderConfig.Account);
}

void TestTradeGateWay::LoadTrader()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} LoadTrader", m_XTraderConfig.Account);
    ReqUserLogin();
}

void TestTradeGateWay::ReLoadTrader()
{
    if(Message::ELoginStatus::ELOGIN_SUCCESSED != m_ConnectedStatus)
    {
        DestroyTraderAPI();
        CreateTraderAPI();
        LoadTrader();

        FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReLoadTrader", m_XTraderConfig.Account);
    }
}

int TestTradeGateWay::ReqQryFund()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqQryFund", m_XTraderConfig.Account);
    EnsureTestFund();
    PublishFund();
    return 0;
}

int TestTradeGateWay::ReqQryPoistion()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqQryPoistion", m_XTraderConfig.Account);
    for(auto it = m_TickerAccountPositionMap.begin(); it != m_TickerAccountPositionMap.end(); ++it)
    {
        PublishPosition(it->second);
    }
    return 0;
}

int TestTradeGateWay::ReqQryTrade()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqQryTrade", m_XTraderConfig.Account);
    return 0;
}

int TestTradeGateWay::ReqQryOrder()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqQryOrder", m_XTraderConfig.Account);
    return 0;
}

int TestTradeGateWay::ReqQryTickerRate()
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqQryTickerRate", m_XTraderConfig.Account);
    return 0;
}

void TestTradeGateWay::ReqInsertOrder(const Message::TOrderRequest& request)
{
    // test 模式在进程内模拟“柜台已成交”回报，目的是完整验证
    // XServer -> XWatcher -> XRiskJudge -> XTrader -> 桌面 的报单闭环。
    EnsureTestFund();
    Message::TAccountFund& fund = m_AccountFundMap[m_XTraderConfig.Account];
    const double notional = request.Price * request.Volume;
    const std::string positionKey = std::string(request.Account) + ":" + request.Ticker;
    Message::TAccountPosition& position = m_TickerAccountPositionMap[positionKey];

    if(request.Direction == Message::EOrderDirection::EBUY && fund.Available < notional)
    {
        Message::TOrderRequest rejected = request;
        rejected.ErrorID = -3001;
        strncpy(rejected.ErrorMsg, "test account has insufficient available cash", sizeof(rejected.ErrorMsg));
        ReqInsertOrderRejected(rejected);
        return;
    }
    if(request.Direction == Message::EOrderDirection::ESELL &&
       position.StockPosition.LongYdPosition < request.Volume)
    {
        Message::TOrderRequest rejected = request;
        rejected.ErrorID = -3002;
        strncpy(rejected.ErrorMsg, "test account has insufficient available shares", sizeof(rejected.ErrorMsg));
        ReqInsertOrderRejected(rejected);
        return;
    }

    Message::TOrderStatus order;
    memset(&order, 0, sizeof(order));
    order.BusinessType = m_XTraderConfig.BusinessType;
    strncpy(order.Product, m_XTraderConfig.Product.c_str(), sizeof(order.Product));
    strncpy(order.Broker, m_XTraderConfig.Broker.c_str(), sizeof(order.Broker));
    strncpy(order.Account, request.Account, sizeof(order.Account));
    strncpy(order.Ticker, request.Ticker, sizeof(order.Ticker));
    strncpy(order.ExchangeID, request.ExchangeID, sizeof(order.ExchangeID));
    fmt::format_to_n(order.OrderRef, sizeof(order.OrderRef), "TEST-{:09d}", request.OrderToken);
    fmt::format_to_n(order.OrderSysID, sizeof(order.OrderSysID), "SIM-{:09d}", request.OrderToken);
    order.OrderToken = request.OrderToken;
    order.EngineID = request.EngineID;
    order.OrderType = request.OrderType;
    order.OrderSide = request.Direction == Message::EOrderDirection::EBUY ?
        Message::EOrderSide::EOPEN_LONG : Message::EOrderSide::ECLOSE_YD_LONG;
    order.OrderStatus = Message::EOrderStatusType::EALLTRADED;
    order.SendPrice = request.Price;
    order.SendVolume = request.Volume;
    order.TotalTradedVolume = request.Volume;
    order.TradedVolume = request.Volume;
    order.TradedPrice = request.Price;
    order.TradedAvgPrice = request.Price;
    strncpy(order.RecvMarketTime, request.RecvMarketTime, sizeof(order.RecvMarketTime));
    strncpy(order.SendTime, request.SendTime, sizeof(order.SendTime));
    strncpy(order.InsertTime, Utils::getCurrentTimeUs(), sizeof(order.InsertTime));
    strncpy(order.BrokerACKTime, order.InsertTime, sizeof(order.BrokerACKTime));
    strncpy(order.ExchangeACKTime, order.InsertTime, sizeof(order.ExchangeACKTime));
    strncpy(order.RiskID, request.RiskID, sizeof(order.RiskID));
    strncpy(order.Trader, "TestTrader", sizeof(order.Trader));

    if(request.Direction == Message::EOrderDirection::EBUY)
    {
        fund.Available -= notional;
        position.StockPosition.LongPosition += request.Volume;
        position.StockPosition.LongTdBuy += request.Volume;
        // 仅为了演示卖出路径，模拟盘按 T+0 提供可卖数量；真实 A 股必须由 ATP
        // 依据 T+1、可用持仓和账户规则给出最终可卖数量。
        position.StockPosition.LongYdPosition += request.Volume;
    }
    else
    {
        fund.Available += notional;
        position.StockPosition.LongPosition -= request.Volume;
        position.StockPosition.LongTdSell += request.Volume;
        position.StockPosition.LongYdPosition -= request.Volume;
    }
    strncpy(position.Account, request.Account, sizeof(position.Account));
    strncpy(position.Ticker, request.Ticker, sizeof(position.Ticker));
    strncpy(position.ExchangeID, request.ExchangeID, sizeof(position.ExchangeID));
    strncpy(position.Product, m_XTraderConfig.Product.c_str(), sizeof(position.Product));
    strncpy(position.Broker, m_XTraderConfig.Broker.c_str(), sizeof(position.Broker));
    position.BusinessType = m_XTraderConfig.BusinessType;
    strncpy(position.UpdateTime, Utils::getCurrentTimeUs(), sizeof(position.UpdateTime));

    m_OrderStatusMap[order.OrderRef] = order;
    UpdateOrderStatus(order);
    PublishFund();
    PublishPosition(position);
    FMTLOG(fmtlog::INF,
           "TraceID={} Stage=TestFill Account={} Ticker={} OrderToken={} Price={} Volume={}",
           Utils::OrderTraceID(order.Account, order.OrderToken, order.OrderRef), order.Account,
           order.Ticker, order.OrderToken, order.TradedPrice, order.TradedVolume);
}

void TestTradeGateWay::ReqInsertOrderRejected(const Message::TOrderRequest& request)
{
    int orderID = (uint64_t(Utils::getTimeSec() + 8 * 3600 - 17 * 3600) % 86400) * 10000;
    // Order Status
    Message::TOrderStatus OrderStatus;
    memset(&OrderStatus, 0, sizeof(OrderStatus));
    OrderStatus.BusinessType = m_XTraderConfig.BusinessType;
    strncpy(OrderStatus.Product, m_XTraderConfig.Product.c_str(), sizeof(OrderStatus.Product));
    strncpy(OrderStatus.Broker, m_XTraderConfig.Broker.c_str(), sizeof(OrderStatus.Broker));
    strncpy(OrderStatus.Account, m_XTraderConfig.Account.c_str(), sizeof(OrderStatus.Account));
    strncpy(OrderStatus.ExchangeID, request.ExchangeID, sizeof(OrderStatus.ExchangeID));
    strncpy(OrderStatus.Ticker, request.Ticker, sizeof(OrderStatus.Ticker));
    fmt::format_to_n(OrderStatus.OrderRef, sizeof(OrderStatus.OrderRef), "{:09d}", orderID);
    strncpy(OrderStatus.RiskID, request.RiskID, sizeof(OrderStatus.RiskID));
    OrderStatus.SendPrice = request.Price;
    OrderStatus.SendVolume = request.Volume;
    OrderStatus.OrderType = request.OrderType;
    OrderStatus.OrderToken = request.OrderToken;
    OrderStatus.EngineID = request.EngineID;
    strncpy(OrderStatus.SendTime, request.SendTime, sizeof(OrderStatus.SendTime));
    strncpy(OrderStatus.InsertTime, Utils::getCurrentTimeUs(), sizeof(OrderStatus.InsertTime));
    strncpy(OrderStatus.RecvMarketTime, request.RecvMarketTime, sizeof(OrderStatus.RecvMarketTime));
    if(Message::ERiskStatusType::ECHECK_INIT == request.RiskStatus)
    {
        OrderStatus.OrderStatus = Message::EOrderStatusType::ERISK_CHECK_INIT;
    }
    else
    {
        OrderStatus.OrderStatus = Message::EOrderStatusType::ERISK_ORDER_REJECTED;
    }
    OrderStatus.ErrorID = request.ErrorID;
    strncpy(OrderStatus.ErrorMsg, request.ErrorMsg, sizeof(OrderStatus.ErrorMsg));
    PrintOrderStatus(OrderStatus, "TestTrader::ReqInsertOrderRejected ");
    UpdateOrderStatus(OrderStatus);
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqInsertOrderRejected", m_XTraderConfig.Account);
}

void TestTradeGateWay::ReqCancelOrder(const Message::TActionRequest& request)
{
    // 测试订单立即全成，因此不存在可撤订单。真实撤单仍由 ATP 网关负责。
    FMTLOG(fmtlog::WRN, "TestTradeGateWay Account:{} cannot cancel already-filled order:{}",
           m_XTraderConfig.Account, request.OrderRef);
}

void TestTradeGateWay::ReqCancelOrderRejected(const Message::TActionRequest& request)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} ReqCancelOrderRejected", m_XTraderConfig.Account);
}

void TestTradeGateWay::RepayMarginDirect(double value)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} RepayMarginDirect", m_XTraderConfig.Account);
}

void TestTradeGateWay::TransferFundIn(double value)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} TransferFundIn", m_XTraderConfig.Account);
}

void TestTradeGateWay::TransferFundOut(double value)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} TransferFundOut", m_XTraderConfig.Account);
}

void TestTradeGateWay::UpdatePosition(const Message::TOrderStatus& OrderStatus, Message::TAccountPosition& Position)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} UpdatePosition", m_XTraderConfig.Account);
}

void TestTradeGateWay::UpdateFund(const Message::TOrderStatus& OrderStatus, Message::TAccountFund& Fund)
{
    FMTLOG(fmtlog::INF, "TestTradeGateWay Account:{} UpdateFund", m_XTraderConfig.Account);
}

void TestTradeGateWay::EnsureTestFund()
{
    Message::TAccountFund& fund = m_AccountFundMap[m_XTraderConfig.Account];
    if(fund.Account[0] != '\0')
    {
        return;
    }
    memset(&fund, 0, sizeof(fund));
    fund.BusinessType = m_XTraderConfig.BusinessType;
    strncpy(fund.Product, m_XTraderConfig.Product.c_str(), sizeof(fund.Product));
    strncpy(fund.Broker, m_XTraderConfig.Broker.c_str(), sizeof(fund.Broker));
    strncpy(fund.Account, m_XTraderConfig.Account.c_str(), sizeof(fund.Account));
    fund.Available = 1000000;
    fund.Balance = 1000000;
    fund.PreBalance = 1000000;
}

void TestTradeGateWay::PublishFund()
{
    Message::TAccountFund& fund = m_AccountFundMap[m_XTraderConfig.Account];
    strncpy(fund.UpdateTime, Utils::getCurrentTimeUs(), sizeof(fund.UpdateTime));
    Message::PackMessage message;
    memset(&message, 0, sizeof(message));
    message.MessageType = Message::EMessageType::EAccountFund;
    memcpy(&message.AccountFund, &fund, sizeof(fund));
    while(!m_ReportMessageQueue.Push(message));
}

void TestTradeGateWay::PublishPosition(const Message::TAccountPosition& position)
{
    Message::PackMessage message;
    memset(&message, 0, sizeof(message));
    message.MessageType = Message::EMessageType::EAccountPosition;
    memcpy(&message.AccountPosition, &position, sizeof(position));
    while(!m_ReportMessageQueue.Push(message));
}
