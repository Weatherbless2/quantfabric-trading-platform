#include "ATPTradeGateWay.h"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdlib>
#include <cstring>
#include <yaml-cpp/yaml.h>
#include "OrderTrace.hpp"
#include "XPluginEngine.hpp"

CreateObjectFunc(ATPTradeGateWay);

namespace
{
template <typename T>
T ValueOr(const YAML::Node& node, const char *key, const T& fallback)
{
    return node[key] ? node[key].as<T>() : fallback;
}

int OrderStatus(const std::string& status)
{
    if(status == "partial") return Message::EOrderStatusType::EPARTTRADED;
    if(status == "filled") return Message::EOrderStatusType::EALLTRADED;
    if(status == "partial_cancelled") return Message::EOrderStatusType::EPARTTRADED_CANCELLED;
    if(status == "cancelled") return Message::EOrderStatusType::ECANCELLED;
    if(status == "rejected") return Message::EOrderStatusType::EEXCHANGE_ERROR;
    return Message::EOrderStatusType::EEXCHANGE_ACK;
}

bool IsTerminalOrderStatus(uint8_t status)
{
    return status == Message::EOrderStatusType::EALLTRADED ||
           status == Message::EOrderStatusType::ECANCELLED ||
           status == Message::EOrderStatusType::EPARTTRADED_CANCELLED ||
           status == Message::EOrderStatusType::EBROKER_ERROR ||
           status == Message::EOrderStatusType::EEXCHANGE_ERROR;
}
}

ATPTradeGateWay::ATPTradeGateWay() :
    m_BridgeHost("127.0.0.1"),
    m_BridgePort(19002),
    m_EnableOrders(false),
    m_Socket(-1),
    m_Stop(false)
{
    m_ConnectedStatus = Message::ELoginStatus::ELOGIN_PREPARED;
}

ATPTradeGateWay::~ATPTradeGateWay()
{
    DestroyTraderAPI();
}

void ATPTradeGateWay::LoadAPIConfig()
{
    try
    {
        YAML::Node config = YAML::LoadFile(m_XTraderConfig.TraderAPIConfig);
        YAML::Node bridge = config["ATPBridgeConfig"];
        if(!bridge)
        {
            FMTLOG(fmtlog::ERR, "ATPTradeGateWay::LoadAPIConfig missing ATPBridgeConfig in {}",
                   m_XTraderConfig.TraderAPIConfig);
            return;
        }
        m_BridgeHost = ValueOr<std::string>(bridge, "Host", "127.0.0.1");
        m_BridgePort = ValueOr<int>(bridge, "Port", 19002);
        m_EnableOrders = ValueOr<bool>(bridge, "EnableOrders", false);
        const char *enableOrders = getenv("QF_ATP_ENABLE_ORDERS");
        if(enableOrders != NULL && std::string(enableOrders) == "1")
        {
            m_EnableOrders = true;
        }
        FMTLOG(fmtlog::INF, "ATPTradeGateWay::LoadAPIConfig Bridge:{}:{} EnableOrders:{}",
               m_BridgeHost, m_BridgePort, m_EnableOrders);
    }
    catch(const std::exception& error)
    {
        FMTLOG(fmtlog::ERR, "ATPTradeGateWay::LoadAPIConfig failed: {}", error.what());
    }
}

void ATPTradeGateWay::GetCommitID(std::string& CommitID, std::string& UtilsCommitID)
{
    CommitID = SO_COMMITID;
    UtilsCommitID = SO_UTILS_COMMITID;
}

void ATPTradeGateWay::GetAPIVersion(std::string& APIVersion)
{
    APIVersion = API_VERSION;
}

int ATPTradeGateWay::ConnectBridge()
{
    int socketFD = socket(AF_INET, SOCK_STREAM, 0);
    if(socketFD < 0)
    {
        return -1;
    }
    sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(m_BridgePort);
    if(inet_pton(AF_INET, m_BridgeHost.c_str(), &address.sin_addr) != 1 ||
       connect(socketFD, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0)
    {
        close(socketFD);
        return -1;
    }
    return socketFD;
}

void ATPTradeGateWay::CreateTraderAPI()
{
    if(m_ReceiveThread.joinable())
    {
        return;
    }
    m_Stop = false;
    m_ReceiveThread = std::thread(&ATPTradeGateWay::ReceiveLoop, this);
}

void ATPTradeGateWay::DestroyTraderAPI()
{
    m_Stop = true;
    {
        std::lock_guard<std::mutex> lock(m_SocketMutex);
        if(m_Socket >= 0)
        {
            shutdown(m_Socket, SHUT_RDWR);
        }
    }
    if(m_ReceiveThread.joinable())
    {
        m_ReceiveThread.join();
    }
    std::lock_guard<std::mutex> lock(m_SocketMutex);
    if(m_Socket >= 0)
    {
        close(m_Socket);
        m_Socket = -1;
    }
    m_ConnectedStatus = Message::ELoginStatus::ELOGIN_FAILED;
}

void ATPTradeGateWay::ReqUserLogin()
{
    // Python 桥已完成 AGW 和客户登录；本插件只等待桥发送 login 状态。
}

void ATPTradeGateWay::LoadTrader()
{
    for(int i = 0; i < 100 && m_ConnectedStatus != Message::ELoginStatus::ELOGIN_SUCCESSED; ++i)
    {
        usleep(100 * 1000);
    }
    FMTLOG(fmtlog::INF, "ATPTradeGateWay::LoadTrader Account:{} Connected:{}",
           m_XTraderConfig.Account,
           m_ConnectedStatus == Message::ELoginStatus::ELOGIN_SUCCESSED);
}

void ATPTradeGateWay::ReLoadTrader()
{
    if(!m_ReceiveThread.joinable())
    {
        CreateTraderAPI();
    }
}

bool ATPTradeGateWay::SendLine(const std::string& line)
{
    std::lock_guard<std::mutex> lock(m_SocketMutex);
    if(m_Socket < 0)
    {
        return false;
    }
    std::string payload = line + "\n";
    return send(m_Socket, payload.data(), payload.size(), MSG_NOSIGNAL) == static_cast<ssize_t>(payload.size());
}

int ATPTradeGateWay::SendQuery(const char *name)
{
    bool ok = SendLine(fmt::format("{{\"type\":\"query\",\"name\":\"{}\"}}", name));
    FMTLOG(ok ? fmtlog::INF : fmtlog::WRN, "ATPTradeGateWay::SendQuery Account:{} Name:{} Sent:{}",
           m_XTraderConfig.Account, name, ok);
    return ok ? 0 : -1;
}

void ATPTradeGateWay::RequestAccountStateRecovery()
{
    // Restore local state from the counter. Pending orders are deliberately
    // not replayed because a reconnect must never create a second order.
    ReqQryFund();
    ReqQryPoistion();
    ReqQryOrder();
    ReqQryTrade();
}

int ATPTradeGateWay::ReqQryFund()
{
    return SendQuery("fund");
}

int ATPTradeGateWay::ReqQryPoistion()
{
    return SendQuery("position");
}

int ATPTradeGateWay::ReqQryTrade()
{
    return SendQuery("trade");
}

int ATPTradeGateWay::ReqQryOrder()
{
    return SendQuery("order");
}

int ATPTradeGateWay::ReqQryTickerRate()
{
    return 0;
}

void ATPTradeGateWay::ReqInsertOrder(const Message::TOrderRequest& request)
{
    if(!m_EnableOrders)
    {
        PublishRejected(request, -2001, "ATPTrader EnableOrders is false");
        return;
    }
    if(request.OrderType != Message::EOrderType::ELIMIT)
    {
        PublishRejected(request, -2003, "ATPTrader only supports limit orders");
        return;
    }
    if(request.Direction != Message::EOrderDirection::EBUY &&
       request.Direction != Message::EOrderDirection::ESELL)
    {
        PublishRejected(request, -2004, "ATPTrader only supports cash buy and sell");
        return;
    }
    if(request.Price <= 0 || request.Volume <= 0)
    {
        PublishRejected(request, -2005, "ATPTrader price and volume must be positive");
        return;
    }
    if(request.OrderToken != 0 &&
       m_SubmittedOrderTokens.find(request.OrderToken) != m_SubmittedOrderTokens.end())
    {
        PublishRejected(request, -2006, "duplicate client order token");
        return;
    }
    std::string payload = fmt::format(
        "{{\"type\":\"order\",\"ticker\":\"{}\",\"exchange\":\"{}\","
        "\"order_type\":{},\"direction\":{},\"price\":{},\"volume\":{},\"engine_id\":{},"
        "\"order_token\":{},\"send_time\":\"{}\"}}",
        request.Ticker, request.ExchangeID, request.OrderType, request.Direction, request.Price, request.Volume,
        request.EngineID, request.OrderToken, request.SendTime);
    FMTLOG(fmtlog::INF,
           "TraceID={} Stage=ATPSend Account={} Ticker={} OrderToken={} Price={} Volume={}",
           Utils::OrderTraceID(request.Account, request.OrderToken), request.Account,
           request.Ticker, request.OrderToken, request.Price, request.Volume);
    // A successful write followed by a broken peer is ambiguous. Keep the
    // token so a retry cannot accidentally create a second counter order.
    if(request.OrderToken != 0)
    {
        m_SubmittedOrderTokens.insert(request.OrderToken);
    }
    if(!SendLine(payload))
    {
        PublishRejected(request, -2002, "ATP bridge is disconnected");
    }
}

void ATPTradeGateWay::PublishRejected(const Message::TOrderRequest& request, int errorID, const char *errorMsg)
{
    Message::TOrderStatus status;
    memset(&status, 0, sizeof(status));
    status.BusinessType = m_XTraderConfig.BusinessType;
    strncpy(status.Product, m_XTraderConfig.Product.c_str(), sizeof(status.Product));
    strncpy(status.Broker, m_XTraderConfig.Broker.c_str(), sizeof(status.Broker));
    strncpy(status.Account, m_XTraderConfig.Account.c_str(), sizeof(status.Account));
    strncpy(status.Ticker, request.Ticker, sizeof(status.Ticker));
    strncpy(status.ExchangeID, request.ExchangeID, sizeof(status.ExchangeID));
    strncpy(status.RiskID, request.RiskID, sizeof(status.RiskID));
    status.SendPrice = request.Price;
    status.SendVolume = request.Volume;
    status.OrderType = request.OrderType;
    status.OrderSide = request.Direction == Message::EOrderDirection::EBUY ?
        Message::EOrderSide::EOPEN_LONG : Message::EOrderSide::ECLOSE_LONG;
    status.OrderToken = request.OrderToken;
    status.EngineID = request.EngineID;
    status.OrderStatus = Message::EOrderStatusType::EBROKER_ERROR;
    status.ErrorID = errorID;
    strncpy(status.ErrorMsg, errorMsg, sizeof(status.ErrorMsg));
    strncpy(status.SendTime, request.SendTime, sizeof(status.SendTime));
    UpdateOrderStatus(status);
}

void ATPTradeGateWay::ReqInsertOrderRejected(const Message::TOrderRequest& request)
{
    PublishRejected(request, request.ErrorID, request.ErrorMsg);
}

void ATPTradeGateWay::ReqCancelOrder(const Message::TActionRequest& request)
{
    if(!m_EnableOrders)
    {
        FMTLOG(fmtlog::WRN, "ATPTradeGateWay::ReqCancelOrder EnableOrders is false, OrderRef:{}", request.OrderRef);
        return;
    }
    auto order = m_OrderStatusMap.find(request.OrderRef);
    std::string exchange = request.ExchangeID;
    if(exchange.empty())
    {
        if(order == m_OrderStatusMap.end())
        {
            FMTLOG(fmtlog::WRN, "ATPTradeGateWay::ReqCancelOrder OrderRef:{} not found", request.OrderRef);
            return;
        }
        exchange = order->second.ExchangeID;
    }
    if(SendLine(fmt::format(
           "{{\"type\":\"cancel\",\"order_ref\":\"{}\",\"exchange\":\"{}\"}}",
           request.OrderRef, exchange)))
    {
        // The counter still owns the final decision.  Mark the local order as
        // cancelling for the desktop, but retain its previous active state so
        // an ATP rejection does not turn a live order into a terminal one.
        Message::TOrderStatus cancelling = order->second;
        {
            std::lock_guard<std::mutex> lock(m_CancelStateMutex);
            m_PreCancelOrderStatusMap[request.OrderRef] = cancelling;
        }
        cancelling.OrderStatus = Message::EOrderStatusType::ECANCELLING;
        cancelling.ErrorID = 0;
        cancelling.ErrorMsg[0] = '\0';
        m_OrderStatusMap[request.OrderRef] = cancelling;
        UpdateOrderStatus(cancelling);
    }
    else
    {
        FMTLOG(fmtlog::ERR, "ATPTradeGateWay::ReqCancelOrder bridge disconnected, OrderRef:{}", request.OrderRef);
        PublishCancelFailure(request.OrderRef, -2002, "ATP bridge is disconnected");
    }
}

void ATPTradeGateWay::PublishCancelFailure(const std::string& orderRef, int errorID, const std::string& errorMsg)
{
    auto order = m_OrderStatusMap.find(orderRef);
    if(order == m_OrderStatusMap.end())
    {
        FMTLOG(fmtlog::WRN, "ATPTradeGateWay::PublishCancelFailure unknown OrderRef:{} ErrorID:{} Error:{}",
               orderRef, errorID, errorMsg);
        return;
    }
    // A final fill/cancel may race with the rejection callback.  The terminal
    // counter result is authoritative and must never be rolled back.
    if(IsTerminalOrderStatus(order->second.OrderStatus))
    {
        std::lock_guard<std::mutex> lock(m_CancelStateMutex);
        m_PreCancelOrderStatusMap.erase(orderRef);
        return;
    }
    Message::TOrderStatus restored = order->second;
    {
        std::lock_guard<std::mutex> lock(m_CancelStateMutex);
        const auto previous = m_PreCancelOrderStatusMap.find(orderRef);
        if(previous != m_PreCancelOrderStatusMap.end())
        {
            restored = previous->second;
            m_PreCancelOrderStatusMap.erase(previous);
        }
    }
    restored.ErrorID = errorID;
    strncpy(restored.ErrorMsg, errorMsg.c_str(), sizeof(restored.ErrorMsg));
    m_OrderStatusMap[orderRef] = restored;
    UpdateOrderStatus(restored);
}

void ATPTradeGateWay::ReqCancelOrderRejected(const Message::TActionRequest& request)
{
    FMTLOG(fmtlog::WRN, "ATPTradeGateWay::ReqCancelOrderRejected OrderRef:{} ErrorID:{} ErrorMsg:{}",
           request.OrderRef, request.ErrorID, request.ErrorMsg);
    auto order = m_OrderStatusMap.find(request.OrderRef);
    if(order == m_OrderStatusMap.end() || IsTerminalOrderStatus(order->second.OrderStatus))
    {
        return;
    }
    // The rejection happened before ATP received a cancel request. Preserve
    // the active order state and attach the reason so it remains retryable.
    Message::TOrderStatus rejected = order->second;
    rejected.ErrorID = request.ErrorID;
    strncpy(rejected.ErrorMsg, request.ErrorMsg, sizeof(rejected.ErrorMsg));
    UpdateOrderStatus(rejected);
}

void ATPTradeGateWay::RepayMarginDirect(double value)
{
    FMTLOG(fmtlog::WRN, "ATPTradeGateWay::RepayMarginDirect unsupported Value:{}", value);
}

void ATPTradeGateWay::TransferFundIn(double value)
{
    FMTLOG(fmtlog::WRN, "ATPTradeGateWay::TransferFundIn unsupported Value:{}", value);
}

void ATPTradeGateWay::TransferFundOut(double value)
{
    FMTLOG(fmtlog::WRN, "ATPTradeGateWay::TransferFundOut unsupported Value:{}", value);
}

void ATPTradeGateWay::HandleMessage(const std::string& line)
{
    try
    {
        YAML::Node data = YAML::Load(line);
        std::string type = ValueOr<std::string>(data, "type", "");
        if(type == "login")
        {
            const bool connected = ValueOr<bool>(data, "connected", false);
            const bool wasConnected = m_ConnectedStatus == Message::ELoginStatus::ELOGIN_SUCCESSED;
            m_ConnectedStatus = connected ? Message::ELoginStatus::ELOGIN_SUCCESSED :
                                            Message::ELoginStatus::ELOGIN_FAILED;
            if(connected && !wasConnected)
            {
                FMTLOG(fmtlog::INF, "ATPTradeGateWay::HandleMessage bridge connected; recovering account state");
                RequestAccountStateRecovery();
            }
        }
        else if(type == "fund")
        {
            Message::TAccountFund fund;
            memset(&fund, 0, sizeof(fund));
            fund.BusinessType = m_XTraderConfig.BusinessType;
            strncpy(fund.Product, m_XTraderConfig.Product.c_str(), sizeof(fund.Product));
            strncpy(fund.Broker, m_XTraderConfig.Broker.c_str(), sizeof(fund.Broker));
            strncpy(fund.Account, m_XTraderConfig.Account.c_str(), sizeof(fund.Account));
            fund.Balance = ValueOr<double>(data, "balance", 0);
            fund.PreBalance = ValueOr<double>(data, "pre_balance", 0);
            fund.Available = ValueOr<double>(data, "available", 0);
            strncpy(fund.UpdateTime, Utils::getCurrentTimeUs(), sizeof(fund.UpdateTime));
            m_AccountFundMap[m_XTraderConfig.Account] = fund;
            Message::PackMessage message;
            memset(&message, 0, sizeof(message));
            message.MessageType = Message::EMessageType::EAccountFund;
            memcpy(&message.AccountFund, &fund, sizeof(fund));
            while(!m_ReportMessageQueue.Push(message));
        }
        else if(type == "position")
        {
            Message::TAccountPosition position;
            memset(&position, 0, sizeof(position));
            position.BusinessType = m_XTraderConfig.BusinessType;
            strncpy(position.Product, m_XTraderConfig.Product.c_str(), sizeof(position.Product));
            strncpy(position.Broker, m_XTraderConfig.Broker.c_str(), sizeof(position.Broker));
            strncpy(position.Account, m_XTraderConfig.Account.c_str(), sizeof(position.Account));
            strncpy(position.Ticker, ValueOr<std::string>(data, "ticker", "").c_str(), sizeof(position.Ticker));
            strncpy(position.ExchangeID, ValueOr<std::string>(data, "exchange", "").c_str(), sizeof(position.ExchangeID));
            position.StockPosition.LongPosition = ValueOr<int>(data, "total", 0);
            // The existing stock position contract uses LongYdPosition for
            // sellable shares. ATP supplies this separately from total shares.
            position.StockPosition.LongYdPosition = ValueOr<int>(data, "available", 0);
            strncpy(position.UpdateTime, Utils::getCurrentTimeUs(), sizeof(position.UpdateTime));
            std::string key = m_XTraderConfig.Account + ":" + position.Ticker;
            m_TickerAccountPositionMap[key] = position;
            Message::PackMessage message;
            memset(&message, 0, sizeof(message));
            message.MessageType = Message::EMessageType::EAccountPosition;
            memcpy(&message.AccountPosition, &position, sizeof(position));
            while(!m_ReportMessageQueue.Push(message));
        }
        else if(type == "order_status")
        {
            Message::TOrderStatus status;
            memset(&status, 0, sizeof(status));
            status.BusinessType = m_XTraderConfig.BusinessType;
            strncpy(status.Product, m_XTraderConfig.Product.c_str(), sizeof(status.Product));
            strncpy(status.Broker, m_XTraderConfig.Broker.c_str(), sizeof(status.Broker));
            strncpy(status.Account, m_XTraderConfig.Account.c_str(), sizeof(status.Account));
            strncpy(status.Ticker, ValueOr<std::string>(data, "ticker", "").c_str(), sizeof(status.Ticker));
            strncpy(status.ExchangeID, ValueOr<std::string>(data, "exchange", "").c_str(), sizeof(status.ExchangeID));
            strncpy(status.OrderRef, ValueOr<std::string>(data, "order_ref", "").c_str(), sizeof(status.OrderRef));
            strncpy(status.OrderSysID, ValueOr<std::string>(data, "order_sys_id", "").c_str(), sizeof(status.OrderSysID));
            status.OrderStatus = OrderStatus(ValueOr<std::string>(data, "status", "accepted"));
            status.OrderSide = ValueOr<int>(data, "side", 1) == 1 ?
                Message::EOrderSide::EOPEN_LONG : Message::EOrderSide::ECLOSE_LONG;
            status.OrderType = ValueOr<int>(data, "order_type", Message::EOrderType::ELIMIT);
            status.SendPrice = ValueOr<double>(data, "price", 0);
            status.SendVolume = ValueOr<int>(data, "volume", 0);
            status.TotalTradedVolume = ValueOr<int>(data, "traded", 0);
            status.TradedPrice = ValueOr<double>(data, "traded_price", 0);
            status.CanceledVolume = ValueOr<int>(data, "cancelled", 0);
            status.EngineID = ValueOr<int>(data, "engine_id", 0);
            status.OrderToken = ValueOr<int>(data, "order_token", 0);
            status.ErrorID = ValueOr<int>(data, "error_id", 0);
            strncpy(status.ErrorMsg, ValueOr<std::string>(data, "error_msg", "").c_str(), sizeof(status.ErrorMsg));
            strncpy(status.SendTime, ValueOr<std::string>(data, "send_time", "").c_str(), sizeof(status.SendTime));
            strncpy(status.UpdateTime, Utils::getCurrentTimeUs(), sizeof(status.UpdateTime));
            FMTLOG(fmtlog::INF,
                   "TraceID={} Stage=ATPCallback Account={} Ticker={} OrderToken={} OrderRef={} Status={} ErrorID={}",
                   Utils::OrderTraceID(status.Account, status.OrderToken, status.OrderRef),
                   status.Account, status.Ticker, status.OrderToken, status.OrderRef,
                   status.OrderStatus, status.ErrorID);
            if(status.OrderRef[0] != '\0')
            {
                auto previous = m_OrderStatusMap.find(status.OrderRef);
                if(previous != m_OrderStatusMap.end())
                {
                    const unsigned int previousTotal = previous->second.TotalTradedVolume;
                    if(status.TotalTradedVolume >= previousTotal)
                    {
                        status.TradedVolume = status.TotalTradedVolume - previousTotal;
                    }
                    else
                    {
                        status.TotalTradedVolume = previousTotal;
                    }
                    status.TradedAvgPrice = previous->second.TradedAvgPrice;
                    if(status.TradedVolume > 0 && status.TradedPrice > 0)
                    {
                        const double previousAmount = previousTotal * previous->second.TradedAvgPrice;
                        status.TradedAvgPrice = (previousAmount + status.TradedVolume * status.TradedPrice) /
                                                status.TotalTradedVolume;
                    }
                }
                else
                {
                    status.TradedVolume = status.TotalTradedVolume;
                    status.TradedAvgPrice = status.TradedPrice;
                }
                m_OrderStatusMap[status.OrderRef] = status;
                if(IsTerminalOrderStatus(status.OrderStatus))
                {
                    std::lock_guard<std::mutex> lock(m_CancelStateMutex);
                    m_PreCancelOrderStatusMap.erase(status.OrderRef);
                }
            }
            UpdateOrderStatus(status);
        }
        else if(type == "command_error")
        {
            FMTLOG(fmtlog::ERR, "ATPTradeGateWay::HandleMessage BridgeError:{}",
                   ValueOr<std::string>(data, "error", "unknown"));
        }
        else if(type == "cancel_error")
        {
            std::string orderRef = ValueOr<std::string>(data, "order_ref", "");
            PublishCancelFailure(orderRef, ValueOr<int>(data, "error_id", -1),
                                 ValueOr<std::string>(data, "error_msg", "ATP cancel failed"));
        }
    }
    catch(const std::exception& error)
    {
        FMTLOG(fmtlog::WRN, "ATPTradeGateWay::HandleMessage invalid payload: {}", error.what());
    }
}

void ATPTradeGateWay::ReceiveLoop()
{
    char buffer[4096];
    std::string pending;
    while(!m_Stop)
    {
        int socketFD = ConnectBridge();
        if(socketFD < 0)
        {
            m_ConnectedStatus = Message::ELoginStatus::ELOGIN_FAILED;
            usleep(500 * 1000);
            continue;
        }
        {
            std::lock_guard<std::mutex> lock(m_SocketMutex);
            m_Socket = socketFD;
        }
        pending.clear();
        ssize_t received = 0;
        while(!m_Stop && (received = recv(socketFD, buffer, sizeof(buffer), 0)) > 0)
        {
            pending.append(buffer, static_cast<size_t>(received));
            size_t newline = std::string::npos;
            while((newline = pending.find('\n')) != std::string::npos)
            {
                HandleMessage(pending.substr(0, newline));
                pending.erase(0, newline + 1);
            }
        }
        {
            std::lock_guard<std::mutex> lock(m_SocketMutex);
            if(m_Socket == socketFD)
            {
                close(m_Socket);
                m_Socket = -1;
            }
        }
        m_ConnectedStatus = Message::ELoginStatus::ELOGIN_FAILED;
    }
}
