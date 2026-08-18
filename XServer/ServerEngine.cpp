#include "ServerEngine.h"
#include "OrderTrace.hpp"
#include "SafeString.hpp"

#include <chrono>
#include <cstdlib>

namespace
{
// These errors originate at XServer before an order reaches the risk engine or
// counter. Keeping them in a separate range makes operational diagnosis clear.
constexpr int kOrderRejectedUnauthorized = -1001;
constexpr int kOrderRejectedOutsideTradingHours = -1002;
constexpr int kOrderRejectedByPublishedPolicy = -1003;
constexpr int kCancelRejectedUnauthorized = -1101;
constexpr int kCancelRejectedByPublishedPolicy = -1102;
}

std::unordered_map<std::string, Message::TLoginResponse> ServerEngine::m_UserPermissionMap;
std::unordered_map<std::string, Message::TAppStatus> ServerEngine::m_AppStatusMap;

ServerEngine::ServerEngine()
{
    m_HPPackServer = NULL;
    m_WorkThread = NULL;
    m_UserDBManager = Utils::Singleton<UserDBManager>::GetInstance();
}

void ServerEngine::LoadConfig(const char* yml)
{
    FMTLOG(fmtlog::INF, "ServerEngine::LoadConfig {} start", yml);
    std::string errorBuffer;
    if(Utils::LoadXServerConfig(yml, m_XServerConfig, errorBuffer))
    {
        FMTLOG(fmtlog::INF, "ServerEngine::LoadXServerConfig {} successed", yml);
        m_OpenTime = Utils::getTimeStampMs(m_XServerConfig.OpenTime.c_str());
        m_CloseTime = Utils::getTimeStampMs(m_XServerConfig.CloseTime.c_str());
        m_AppCheckTime = Utils::getTimeStampMs(m_XServerConfig.AppCheckTime.c_str());
        m_AppStatusStoreTime = Utils::getTimeStampMs(m_XServerConfig.AppStatusStoreTime.c_str());

        if(Utils::endWith(m_XServerConfig.BinPath, ".bin"))
        {
            m_SnapShotPath = m_XServerConfig.BinPath;
        }
        else
        {
            m_SnapShotPath = m_XServerConfig.BinPath + "/" + Utils::getCurrentNumberDay() + ".bin";
        }

        bool ret = m_UserDBManager->LoadDataBase(m_XServerConfig.UserDBPath, errorBuffer);
        if(!ret)
        {
            FMTLOG(fmtlog::ERR, "ServerEngine::LoadDataBase {} failed, {}", m_XServerConfig.UserDBPath, errorBuffer);
        }
        else
        {
            const char* internalKey = getenv("QF_AUTH_INTERNAL_KEY");
            if(m_XServerConfig.AuthorizationEnabled)
            {
                if(!internalKey || !*internalKey)
                {
                    FMTLOG(fmtlog::ERR, "XServer authorization is enabled but QF_AUTH_INTERNAL_KEY is missing");
                }
                else
                {
                    m_AuthzClient = std::make_unique<AuthzClient>(m_XServerConfig.AuthorizationURL,
                            internalKey, m_XServerConfig.AuthorizationTimeoutMs);
                    FMTLOG(fmtlog::INF, "XServer authorization enabled, URL:{} Domain:{} Timeout:{}ms",
                           m_XServerConfig.AuthorizationURL, m_XServerConfig.AuthorizationDomain,
                           m_XServerConfig.AuthorizationTimeoutMs);
                }
            }
            if(m_XServerConfig.BusinessPolicyEnabled)
            {
                if(!internalKey || !*internalKey)
                {
                    FMTLOG(fmtlog::ERR, "XServer business policy is enabled but QF_AUTH_INTERNAL_KEY is missing");
                }
                else
                {
                    m_RuntimePolicyClient = std::make_unique<RuntimePolicyClient>(
                        m_XServerConfig.BusinessPolicyURL, internalKey, m_XServerConfig.BusinessPolicyTimeoutMs);
                    if(!ReloadPublishedPolicy())
                    {
                        FMTLOG(fmtlog::ERR,
                               "XServer business policy initial load failed; published configuration admission is fail-closed");
                    }
                }
            }
            // Load Permission
            m_UserDBManager->QueryUserPermission(&ServerEngine::sqlite3_callback_UserPermission, errorBuffer);
            // Load AppStatus
            m_UserDBManager->QueryAppStatus(&ServerEngine::sqlite3_callback_AppStatus, errorBuffer);
        }
    }
    else
    {
        FMTLOG(fmtlog::ERR, "ServerEngine::LoadXServerConfig {} failed, {}", yml, errorBuffer);
    }
}

void ServerEngine::RegisterServer(const char *ip, unsigned int port)
{
    m_HPPackServer = new HPPackServer(ip, port);
    m_HPPackServer->Start();
}

void ServerEngine::Run()
{
    RegisterServer(m_XServerConfig.ServerIP.c_str(), m_XServerConfig.Port);
    sleep(1);
    if(m_XServerConfig.BusinessPolicyEnabled && m_RuntimePolicyClient)
    {
        m_RuntimePolicyRefreshThread = new std::thread(&ServerEngine::RunPublishedPolicyRefresh, this);
    }
    m_WorkThread = new std::thread(&ServerEngine::WorkFunc, this);
    m_WorkThread->join();
}

void ServerEngine::WorkFunc()
{
    // XServer 是中心路由器：收集各 Colo 的上行数据，按用户权限转发给 XMonitor，
    // 同时把 GUI 控制命令下发到目标 XWatcher。
    // 发送EventLog
    memset(&m_PackMessage, 0, sizeof(m_PackMessage));
    m_PackMessage.MessageType = Message::EMessageType::EEventLog;
    m_PackMessage.EventLog.Level = Message::EEventLogLevel::EINFO;
    strncpy(m_PackMessage.EventLog.App, "XServer", sizeof(m_PackMessage.EventLog.App));
    fmt::format_to_n(m_PackMessage.EventLog.Event, sizeof(m_PackMessage.EventLog.Event), 
                    "XServer Start, listen:{}:{}",
                    m_XServerConfig.ServerIP, m_XServerConfig.Port);
    strncpy(m_PackMessage.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(m_PackMessage.EventLog.UpdateTime));
    HandleEventLog(m_PackMessage);
    // Load Snap Shot
    if(m_XServerConfig.SnapShot)
    {
        std::vector<Message::PackMessage> items;
        if(Utils::SnapShotHelper<Message::PackMessage>::LoadSnapShot(m_SnapShotPath, items))
        {
            FMTLOG(fmtlog::INF, "ServerEngine::LoadSnapShot {} successed, SnapShot number:{}", m_SnapShotPath, items.size());
            for (size_t i = 0; i < items.size(); i++)
            {
                memcpy(&m_PackMessage, &items.at(i), sizeof(m_PackMessage));
                HandleSnapShotMessage(m_PackMessage);
            }
        }
        else
        {
            FMTLOG(fmtlog::WRN, "ServerEngine::LoadSnapShot {} failed", m_SnapShotPath);
        }
    }

    FMTLOG(fmtlog::INF, "ServerEngine::Run start to handle message");
    while (true)
    {
        CheckTrading();
        bool handledMessage = false;
        InboundMessage inbound{};
        while(m_HPPackServer->m_PackMessageQueue.Pop(inbound))
        {
            handledMessage = true;
            m_PackMessage = inbound.Message;
            if(m_XServerConfig.SnapShot)
            {
                int retCode = Utils::SnapShotHelper<Message::PackMessage>::WriteData(m_SnapShotPath, m_PackMessage);
                FMTLOG(fmtlog::DBG, "ServerEngine::SnapShotHelper::WriteData result:{}", retCode);
            }
            // 根据 PackMessage 类型进入行情、订单、风控或控制命令的分流处理。
            HandlePackMessage(inbound);
        }
        // History Data Replay 
        HistoryDataReplay();
        // Check App Status when 09:20:00
        CheckAppStatus();
        // Update AppStatus to SQLite when 15:20:00
        UpdateAppStatusTable();
        // The network callback owns message ingestion. Yield briefly when it
        // has no work so an idle XServer does not consume an entire CPU core.
        if(!handledMessage)
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
}

void ServerEngine::HandlePackMessage(const InboundMessage& inbound)
{
    const Message::PackMessage& msg = inbound.Message;
    unsigned int type = msg.MessageType;
    switch (type)
    {
    case Message::ELoginRequest:
        // XMonitor 登录成功后，连接会携带可见插件和允许订阅的消息类型。
        HandleLoginRequest(msg, inbound.ConnectionID);
        break;
    case Message::ECommand:
        // GUI 命令沿 XServer -> XWatcher 的方向下发。
        HandleCommand(msg, inbound.ConnectionID);
        break;
    case Message::EEventLog:
        HandleEventLog(msg);
        break;
    case Message::EAccountFund:
        HandleAccountFund(msg);
        break;
    case Message::EAccountPosition:
        HandleAccountPosition(msg);
        break;
    case Message::EOrderStatus:
        HandleOrderStatus(msg);
        break;
    case Message::EOrderRequest:
        // GUI 手工报单不是本地执行；按 Colo 转给对应的 XWatcher。
        HandleOrderRequest(msg, inbound.ConnectionID);
        break;
    case Message::EActionRequest:
        HandleActionRequest(msg, inbound.ConnectionID);
        break;
    case Message::ERiskReport:
        HandleRiskReport(msg);
        break;
    case Message::EColoStatus:
        HandleColoStatus(msg);
        break;
    case Message::EAppStatus:
        HandleAppStatus(msg);
        break;
    case Message::EFutureMarketData:
        // 行情、回报等上行数据会在对应处理器中缓存最新值并按订阅权限推送。
        HandleFutureMarketData(msg);
        break;
    case Message::EStockMarketData:
        HandleStockMarketData(msg);
        break;
    case Message::ESpotMarketData:
        HandleSpotMarketData(msg);
        break;
    default:
        FMTLOG(fmtlog::WRN, "ServerEngine::HandlePackMessage unkown message type:{:#X}", msg.MessageType);
        break;
    }
}

void ServerEngine::HandleLoginRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection)
{
    if(Message::EClientType::EXMONITOR != msg.LoginRequest.ClientType)
        return;
    auto connection = m_HPPackServer->m_sConnections.find(sourceConnection);
    if(connection == m_HPPackServer->m_sConnections.end())
    {
        FMTLOG(fmtlog::WRN, "ServerEngine::HandleLoginRequest unknown connection:{}", sourceConnection);
        return;
    }

    if(m_XServerConfig.AuthorizationEnabled)
    {
        Message::PackMessage response{};
        response.MessageType = Message::EMessageType::ELoginResponse;
        response.LoginResponse.ClientType = Message::EClientType::EXMONITOR;
        strncpy(response.LoginResponse.Account, msg.LoginRequest.Account, sizeof(response.LoginResponse.Account));
        AuthSessionInfo session;
        const std::string sessionID(msg.LoginRequest.UUID,
                                    strnlen(msg.LoginRequest.UUID, sizeof(msg.LoginRequest.UUID)));
        const std::string requestedAccount(msg.LoginRequest.Account,
                                           strnlen(msg.LoginRequest.Account, sizeof(msg.LoginRequest.Account)));
        const bool valid = m_AuthzClient && sessionID.size() == 30 &&
            m_AuthzClient->ValidateSession(sessionID, session) &&
            session.UserName == requestedAccount;
        if(!valid)
        {
            response.LoginResponse.ErrorID = 0X1001;
            const std::string error = session.Error.empty() ? "invalid authorization session" : session.Error;
            strncpy(response.LoginResponse.ErrorMsg, error.c_str(), sizeof(response.LoginResponse.ErrorMsg));
            m_HPPackServer->SendData(sourceConnection, reinterpret_cast<const unsigned char*>(&response), sizeof(response));
            FMTLOG(fmtlog::WRN, "ServerEngine::HandleLoginRequest authorization rejected connection:{} account:{}",
                   sourceConnection, msg.LoginRequest.Account);
            return;
        }

        connection->second.Authenticated = true;
        strncpy(connection->second.Actor, session.Actor.c_str(), sizeof(connection->second.Actor));
        strncpy(connection->second.SessionID, sessionID.c_str(), sizeof(connection->second.SessionID));
        strncpy(connection->second.Account, session.UserName.c_str(), sizeof(connection->second.Account));
        // Existing monitor forwarding is retained, while account/order and market delivery
        // are constrained below by Casbin decisions and explicit subscriptions.
        const char* plugins = "Market|OrderManager|EventLog|Monitor|RiskJudge|FutureAnalysis|StockAnalysis";
        const char* messages = "FutureMarket|StockMarket|SpotMarket|OrderStatus|AccountFund|AccountPosition|EventLog|ColoStatus|AppStatus|RiskReport";
        strncpy(connection->second.Plugins, plugins, sizeof(connection->second.Plugins));
        strncpy(connection->second.Messages, messages, sizeof(connection->second.Messages));
        m_HPPackServer->m_newConnections[sourceConnection] = connection->second;
        m_MarketSubscriptions[sourceConnection].clear();

        response.LoginResponse.ErrorID = 0;
        strncpy(response.LoginResponse.Account, session.UserName.c_str(), sizeof(response.LoginResponse.Account));
        strncpy(response.LoginResponse.Role, "Authenticated", sizeof(response.LoginResponse.Role));
        strncpy(response.LoginResponse.Plugins, plugins, sizeof(response.LoginResponse.Plugins));
        strncpy(response.LoginResponse.Messages, messages, sizeof(response.LoginResponse.Messages));
        strncpy(response.LoginResponse.UpdateTime, Utils::getCurrentTimeUs(), sizeof(response.LoginResponse.UpdateTime));
        m_HPPackServer->SendData(sourceConnection, reinterpret_cast<const unsigned char*>(&response), sizeof(response));
        FMTLOG(fmtlog::INF, "ServerEngine::HandleLoginRequest authorization accepted connection:{} actor:{}",
               sourceConnection, session.Actor);
        return;
    }

    std::string Account = msg.LoginRequest.Account;
    auto it = m_UserPermissionMap.find(Account);
    if(m_UserPermissionMap.end() != it)
    {
        std::string Plugins = it->second.Plugins;
        std::string errorString;
        for (auto it1 = m_HPPackServer->m_sConnections.begin(); it1 != m_HPPackServer->m_sConnections.end(); ++it1)
        {
            // A user may have multiple monitor sessions. Route the login
            // response back to the exact socket identified by its UUID.
            if(Utils::equalWith(Account, it1->second.Account) &&
               Utils::equalWith(msg.LoginRequest.UUID, it1->second.UUID))
            {
                if (Utils::equalWith(msg.LoginRequest.PassWord, it->second.PassWord))
                {
                    it->second.ErrorID = 0;
                    errorString.clear();
                    strncpy(it->second.ErrorMsg, "Login Successed.", sizeof(it->second.ErrorMsg));
                }
                else
                {
                    {
                        // send LoginResponse
                        Message::PackMessage message;
                        memset(&message, 0, sizeof(message));
                        message.MessageType = Message::EMessageType::ELoginResponse;
                        it->second.ErrorID = 0X1000;
                        sprintf(it->second.ErrorMsg, "Login Failed, Invalid Password");
                        memcpy(&message.LoginResponse, &it->second, sizeof(message.LoginResponse));
                        m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char*)&message, sizeof(message));
                    }
                    {
                        char errorString[256] = {0};
                        sprintf(errorString, "%s Login Failed, Invalid Password", Account.c_str());
                        Message::PackMessage message;
                        memset(&message, 0, sizeof(message));
                        message.MessageType = Message::EMessageType::EEventLog;
                        message.EventLog.Level = Message::EEventLogLevel::EERROR;
                        strncpy(message.EventLog.App, "XServer", sizeof(message.EventLog.App));
                        strncpy(message.EventLog.Event, errorString, sizeof(message.EventLog.Event));
                        strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
                        m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char*)&message, sizeof(message));
                        FMTLOG(fmtlog::WRN, "{} Login Failed, Invalid Password", Account);
                    }
                    return;
                }
                if(Utils::equalWith(it1->second.Account, "root") || Utils::equalWith(it1->second.Account, "admin"))
                {
                    if(Plugins.find(PLUGIN_PERMISSION) == std::string::npos)
                    {
                        if(Plugins.length() > 0)
                        {
                            Plugins += "|";
                        }
                        Plugins += PLUGIN_PERMISSION;
                    }
                }
                strncpy(it->second.Plugins, Plugins.c_str(), sizeof(it->second.Plugins));
                strncpy(it1->second.Plugins, Plugins.c_str(), sizeof(it1->second.Plugins));
                strncpy(it1->second.Messages, it->second.Messages, sizeof(it1->second.Messages));
                // add new connection
                m_HPPackServer->m_newConnections.insert(std::pair<HP_CONNID, Connection>(it1->second.dwConnID, it1->second));
                {
                    // send LoginResponse
                    Message::PackMessage message;
                    memset(&message, 0, sizeof(message));
                    message.MessageType = Message::EMessageType::ELoginResponse;
                    memcpy(&message.LoginResponse, &it->second, sizeof(message.LoginResponse));
                    m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char*)&message, sizeof(message));
                }
                if(Utils::equalWith(it1->second.Account, "root") || Utils::equalWith(it1->second.Account, "admin"))
                {
                    for (auto it3 = m_UserPermissionMap.begin(); it3 != m_UserPermissionMap.end(); it3++)
                    {
                        Message::PackMessage message;
                        memset(&message, 0, sizeof(message));
                        message.MessageType = Message::EMessageType::ELoginResponse;
                        memcpy(&message.LoginResponse, &it3->second, sizeof(message.LoginResponse));
                        m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char*)&message, sizeof(message));
                        FMTLOG(fmtlog::INF, "ServerEngine::HandleLoginRequest UserName:{} Role:{} Plugins:{}",
                                it3->second.Account, it3->second.Role, it3->second.Plugins);
                    }
                }
                break;
            }
            else
            {
                errorString = "Account or UUID not matched.";
            }
        }
        FMTLOG(fmtlog::INF, "ServerEngine::HandleLoginRequest new Connection, Account:{} UUID:{} newConnections:{} errorMsg:{}",
                msg.LoginRequest.Account, msg.LoginRequest.UUID, m_HPPackServer->m_newConnections.size(), errorString);
    }
    else
    {
        FMTLOG(fmtlog::WRN, "ServerEngine::HandleLoginRequest UserName:{} not Found ,mapSize:{}", Account, m_UserPermissionMap.size());
    }
}

void ServerEngine::HandleCommand(const Message::PackMessage &msg, HP_CONNID sourceConnection)
{
    if(Message::ECommandType::EMARKET_SUBSCRIBE == msg.Command.CmdType)
    {
        const std::string request(msg.Command.Command);
        const size_t separator = request.find('|');
        if(separator == std::string::npos)
        {
            SendAuthorizationError(sourceConnection, "invalid market subscription");
            return;
        }
        const std::string ticker = request.substr(0, separator);
        const std::string exchange = request.substr(separator + 1);
        const std::string resource = "market/" + exchange + "/instrument/" + ticker;
        if(!Authorize(sourceConnection, resource, "market:subscribe"))
        {
            SendAuthorizationError(sourceConnection, "market subscription is not authorized");
            return;
        }
        std::string policyError;
        if(!AuthorizePublishedPolicyForSubscription(ticker, exchange, policyError))
        {
            SendAuthorizationError(sourceConnection, policyError);
            FMTLOG(fmtlog::WRN, "XServer published policy rejected market subscription ticker:{} exchange:{} error:{}",
                   ticker, exchange, policyError);
            return;
        }
        m_MarketSubscriptions[sourceConnection].insert(ticker + "." + exchange);
    }
    // Handle UserPermission
    if(Message::ECommandType::EUPDATE_USERPERMISSION == msg.Command.CmdType)
    {
        if(m_XServerConfig.AuthorizationEnabled)
        {
            SendAuthorizationError(sourceConnection, "legacy user-permission updates are disabled");
            FMTLOG(fmtlog::WRN, "XServer rejected legacy permission update from connection:{}", sourceConnection);
            return;
        }
        // Update UserPermission Table
        UpdateUserPermissionTable(msg);
        FMTLOG(fmtlog::DBG, "ServerEngine::HandleCommand Update UserPermission Table:{}", msg.Command.Command);
    }
    // forward to XWatcher
    else if(Message::ECommandType::EUPDATE_RISK_LIMIT == msg.Command.CmdType ||
            Message::ECommandType::EUPDATE_RISK_ACCOUNT_LOCKED == msg.Command.CmdType ||
            Message::ECommandType::EMARKET_SUBSCRIBE == msg.Command.CmdType)
    {
        if(Message::ECommandType::EMARKET_SUBSCRIBE != msg.Command.CmdType &&
           !Authorize(sourceConnection, "risk-limit/" + Utils::ToString(msg.Command.Colo), "risk:update"))
        {
            SendAuthorizationError(sourceConnection, "risk update is not authorized");
            return;
        }
        for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
        {
            std::string Colo = it->second.Colo;
            if(Message::EClientType::EXWATCHER == it->second.ClientType && Colo == msg.Command.Colo)
            {
                m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
                FMTLOG(fmtlog::DBG, "ServerEngine::HandleCommand Send Data to Connection:{} Colo:{}, Account:{}, MessgeType:{:#X}",
                        it->second.dwConnID, Colo, it->second.Account, msg.MessageType);
            }
        }
    }
    // forward to XWatcher
    else if(Message::ECommandType::EKILL_APP == msg.Command.CmdType || Message::ECommandType::ESTART_APP == msg.Command.CmdType)
    {
        if(!Authorize(sourceConnection, "colo/" + Utils::ToString(msg.Command.Colo), "app:manage"))
        {
            SendAuthorizationError(sourceConnection, "application management is not authorized");
            return;
        }
        for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
        {
            std::string Colo = it->second.Colo;
            if (Message::EClientType::EXWATCHER == it->second.ClientType && Colo == msg.Command.Colo)
            {
                m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
                FMTLOG(fmtlog::DBG, "ServerEngine::HandleCommand Send Data to Connection:{} Colo:{}, Account:{}, MessgeType:{:#X}",
                        it->second.dwConnID, Colo, it->second.Account, msg.MessageType);
            }
        }
    }
    // forward to XWatcher
    else if(Message::ECommandType::ETRANSFER_FUND_IN == msg.Command.CmdType 
            || Message::ECommandType::ETRANSFER_FUND_OUT == msg.Command.CmdType
            || Message::ECommandType::EREPAY_MARGIN_DIRECT == msg.Command.CmdType)
    {
        if(!Authorize(sourceConnection, "account/" + Utils::ToString(msg.Command.Account), "fund:transfer"))
        {
            SendAuthorizationError(sourceConnection, "fund operation is not authorized");
            return;
        }
        for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
        {
            std::string Colo = it->second.Colo;
            if (Message::EClientType::EXWATCHER == it->second.ClientType && Colo == msg.Command.Colo)
            {
                m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
                FMTLOG(fmtlog::DBG, "ServerEngine::HandleCommand Send Data to Connection:{} Colo:{}, Account:{}, MessgeType:{:#X}",
                        it->second.dwConnID, Colo, it->second.Account, msg.MessageType);
            }
        }
    }
}

void ServerEngine::HandleEventLog(const Message::PackMessage &msg)
{
    m_EventgLogHistoryQueue.push_back(msg);

    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_EVENTLOG) != std::string::npos)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleEventLog Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleAccountFund(const Message::PackMessage &msg)
{
    m_AccountFundHistoryQueue.push_back(msg);
    std::string Account = msg.AccountFund.Account;
    m_LastAccountFundMap[Account] = msg;
    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_ACCOUNTFUND) != std::string::npos &&
            Authorize(it->second.dwConnID, "account/" + Account, "account:read"))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleAccountFund Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleAccountPosition(const Message::PackMessage &msg)
{
    m_AccountPositionHistoryQueue.push_back(msg);
    std::string Account = msg.AccountPosition.Account;
    std::string Ticker = msg.AccountPosition.Ticker;
    std::string Key = Account + ":" + Ticker;
    m_LastAccountPostionMap[Key] = msg;
    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if(Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_ACCOUNTPOSITION) != std::string::npos &&
           Authorize(it->second.dwConnID, "account/" + Account, "account:read"))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleAccountPosition Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleOrderStatus(const Message::PackMessage &msg)
{
    FMTLOG(fmtlog::INF,
           "TraceID={} Stage=XServerOrderStatus Account={} Ticker={} OrderToken={} OrderRef={} Status={} ErrorID={}",
           Utils::OrderTraceID(msg.OrderStatus.Account, msg.OrderStatus.OrderToken, msg.OrderStatus.OrderRef),
           msg.OrderStatus.Account, msg.OrderStatus.Ticker, msg.OrderStatus.OrderToken,
           msg.OrderStatus.OrderRef, msg.OrderStatus.OrderStatus, msg.OrderStatus.ErrorID);
    m_OrderStatusHistoryQueue.push_back(msg);
    UpdateOrderReference(msg.OrderStatus);
    const std::string Account = msg.OrderStatus.Account;
    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_ORDERSTATUS) != std::string::npos &&
            Authorize(it->second.dwConnID, "account/" + Account, "order:read"))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleOrderStatus Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleOrderRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection)
{
    const std::string traceID = Utils::OrderTraceID(msg.OrderRequest.Account, msg.OrderRequest.OrderToken);
    if(!Authorize(sourceConnection, "account/" + Utils::ToString(msg.OrderRequest.Account), "order:create", traceID))
    {
        SendAuthorizationError(sourceConnection, "order submission is not authorized");
        SendOrderRejected(sourceConnection, msg.OrderRequest, kOrderRejectedUnauthorized,
                          "order submission is not authorized");
        FMTLOG(fmtlog::WRN, "TraceID={} Stage=XServerAuthorize Result=DENY Action=order:create Account={}",
               traceID, msg.OrderRequest.Account);
        return;
    }
    if(!IsTrading())
    {
        SendOrderRejected(sourceConnection, msg.OrderRequest, kOrderRejectedOutsideTradingHours,
                          "order submission is outside configured trading hours");
        FMTLOG(fmtlog::WRN,
               "TraceID={} Stage=XServerTradingHours Result=DENY Account={} Ticker={} OpenTime={} CloseTime={}",
               traceID, msg.OrderRequest.Account, msg.OrderRequest.Ticker,
               m_XServerConfig.OpenTime, m_XServerConfig.CloseTime);
        return;
    }
    std::string policyError;
    if(!AuthorizePublishedPolicyForOrder(msg.OrderRequest, policyError))
    {
        SendAuthorizationError(sourceConnection, policyError);
        SendOrderRejected(sourceConnection, msg.OrderRequest, kOrderRejectedByPublishedPolicy, policyError);
        FMTLOG(fmtlog::WRN, "TraceID={} Stage=XServerPublishedPolicy Result=DENY Account={} Ticker={} Error={}",
               traceID, msg.OrderRequest.Account, msg.OrderRequest.Ticker, policyError);
        return;
    }
    // forward to XWatcher
    for(auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); it++)
    {
        std::string Colo = it->second.Colo;
        if(Message::EClientType::EXWATCHER == it->second.ClientType && Colo == msg.OrderRequest.Colo)
        {
            FMTLOG(fmtlog::INF,
                   "TraceID={} Stage=XServerForward Account={} Ticker={} OrderToken={} Connection={} Colo={}",
                   Utils::OrderTraceID(msg.OrderRequest.Account, msg.OrderRequest.OrderToken),
                   msg.OrderRequest.Account, msg.OrderRequest.Ticker, msg.OrderRequest.OrderToken,
                   it->second.dwConnID, Colo);
            m_HPPackServer->SendData(it->second.dwConnID, reinterpret_cast<const unsigned char*>(&msg), sizeof(msg));
        }
        else if(Message::EClientType::EHFTRADER == it->second.ClientType && Colo == msg.OrderRequest.Colo)
        {
            FMTLOG(fmtlog::INF,
                   "TraceID={} Stage=XServerForwardHF Account={} Ticker={} OrderToken={} Connection={} Colo={}",
                   Utils::OrderTraceID(msg.OrderRequest.Account, msg.OrderRequest.OrderToken),
                   msg.OrderRequest.Account, msg.OrderRequest.Ticker, msg.OrderRequest.OrderToken,
                   it->second.dwConnID, Colo);
            m_HPPackServer->SendData(it->second.dwConnID, reinterpret_cast<const unsigned char*>(&msg), sizeof(msg));
        }
    }
}

void ServerEngine::HandleActionRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection)
{
    const std::string traceID = Utils::OrderTraceID(msg.ActionRequest.Account, 0, msg.ActionRequest.OrderRef);
    if(!Authorize(sourceConnection, "account/" + Utils::ToString(msg.ActionRequest.Account), "order:cancel", traceID))
    {
        SendAuthorizationError(sourceConnection, "order cancellation is not authorized");
        SendCancelRejected(sourceConnection, msg.ActionRequest, kCancelRejectedUnauthorized,
                           "order cancellation is not authorized");
        FMTLOG(fmtlog::WRN, "TraceID={} Stage=XServerAuthorize Result=DENY Action=order:cancel Account={}",
               traceID, msg.ActionRequest.Account);
        return;
    }
    std::string policyError;
    if(!AuthorizePublishedPolicyForCancel(msg.ActionRequest, policyError))
    {
        SendAuthorizationError(sourceConnection, policyError);
        SendCancelRejected(sourceConnection, msg.ActionRequest, kCancelRejectedByPublishedPolicy, policyError);
        FMTLOG(fmtlog::WRN, "TraceID={} Stage=XServerPublishedPolicy Result=DENY Action=order:cancel Account={} Error={}",
               traceID, msg.ActionRequest.Account, policyError);
        return;
    }
    // forward to XWatcher
    for(auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); it++)
    {
        std::string Colo = it->second.Colo;
        if(Message::EClientType::EXWATCHER == it->second.ClientType && Colo == msg.ActionRequest.Colo)
        {
            FMTLOG(fmtlog::INF,
                   "TraceID={} Stage=XServerCancelForward Account={} OrderRef={} Connection={} Colo={}",
                   Utils::OrderTraceID(msg.ActionRequest.Account, 0, msg.ActionRequest.OrderRef),
                   msg.ActionRequest.Account, msg.ActionRequest.OrderRef,
                   it->second.dwConnID, Colo);
            m_HPPackServer->SendData(it->second.dwConnID, reinterpret_cast<const unsigned char*>(&msg), sizeof(msg));
        }
        else if(Message::EClientType::EHFTRADER == it->second.ClientType && Colo == msg.ActionRequest.Colo)
        {
            m_HPPackServer->SendData(it->second.dwConnID, reinterpret_cast<const unsigned char*>(&msg), sizeof(msg));
            FMTLOG(fmtlog::INF, "ServerEngine::HandleActionRequest send Action Request to HFTrader connection:{} Colo:{} Account:{}", 
                    it->second.dwConnID, Colo, it->second.Account);
        }
    }
}

bool ServerEngine::Authorize(HP_CONNID sourceConnection, const std::string& resource,
                             const std::string& action, const std::string& traceID)
{
    if(!m_XServerConfig.AuthorizationEnabled)
    {
        return true;
    }
    const auto connection = m_HPPackServer->m_sConnections.find(sourceConnection);
    if(connection == m_HPPackServer->m_sConnections.end())
    {
        FMTLOG(fmtlog::WRN, "XServer authorization denied unknown connection:{} action:{} resource:{}",
               sourceConnection, action, resource);
        return false;
    }
    // Sensitive control messages may only originate from an authenticated
    // desktop session. Colo services publish data to XServer but never need to
    // issue these commands, so accepting their self-declared ClientType here
    // would let an untrusted TCP client bypass Casbin.
    if(connection->second.ClientType != Message::EClientType::EXMONITOR ||
       !connection->second.Authenticated || !m_AuthzClient)
    {
        FMTLOG(fmtlog::WRN, "XServer authorization denied unauthenticated connection:{} action:{} resource:{}",
               sourceConnection, action, resource);
        return false;
    }
    std::string error;
    const bool allowed = m_AuthzClient->Authorize(connection->second.SessionID,
            m_XServerConfig.AuthorizationDomain, resource, action, traceID, error);
    FMTLOG(allowed ? fmtlog::INF : fmtlog::WRN,
           "TraceID={} Stage=XServerAuthorize Result={} Actor={} Action={} Resource={} Error={}",
           traceID, allowed ? "ALLOW" : "DENY", connection->second.Actor,
           action, resource, error);
    return allowed;
}

bool ServerEngine::HasMarketSubscription(HP_CONNID connection, const std::string& ticker,
                                         const std::string& exchange) const
{
    if(!m_XServerConfig.AuthorizationEnabled)
    {
        return true;
    }
    const auto subscriptions = m_MarketSubscriptions.find(connection);
    return subscriptions != m_MarketSubscriptions.end() &&
        subscriptions->second.find(ticker + "." + exchange) != subscriptions->second.end();
}

bool ServerEngine::AuthorizePublishedPolicyForSubscription(const std::string& ticker, const std::string& exchange,
                                                           std::string& error) const
{
    if(!m_XServerConfig.BusinessPolicyEnabled)
    {
        return true;
    }
    std::shared_lock<std::shared_mutex> lock(m_RuntimePolicyMutex);
    if(!m_RuntimePolicy)
    {
        error = "published business configuration is unavailable";
        return false;
    }
    return m_RuntimePolicy->CanSubscribe(ticker, exchange, error);
}

bool ServerEngine::AuthorizePublishedPolicyForOrder(const Message::TOrderRequest& request,
                                                    std::string& error) const
{
    if(!m_XServerConfig.BusinessPolicyEnabled)
    {
        return true;
    }
    std::shared_lock<std::shared_mutex> lock(m_RuntimePolicyMutex);
    if(!m_RuntimePolicy)
    {
        error = "published business configuration is unavailable";
        return false;
    }
    return m_RuntimePolicy->CanOrder(request.Account, request.Product, request.Ticker, request.ExchangeID,
                                     request.Direction, request.Price, request.Volume, error);
}

bool ServerEngine::AuthorizePublishedPolicyForCancel(const Message::TActionRequest& request,
                                                     std::string& error) const
{
    if(!m_XServerConfig.BusinessPolicyEnabled)
    {
        return true;
    }
    std::shared_lock<std::shared_mutex> lock(m_RuntimePolicyMutex);
    if(!m_RuntimePolicy)
    {
        error = "published business configuration is unavailable";
        return false;
    }
    const auto reference = m_OrderReferences.find(OrderReferenceKey(request.Account, request.OrderRef));
    if(reference == m_OrderReferences.end())
    {
        error = "order reference is unknown or no longer cancellable";
        return false;
    }
    return m_RuntimePolicy->CanCancel(request.Account, reference->second.Product,
                                      reference->second.Ticker, reference->second.Exchange, error);
}

void ServerEngine::UpdateOrderReference(const Message::TOrderStatus& status)
{
    if(status.OrderRef[0] == '\0')
    {
        return;
    }
    const std::string key = OrderReferenceKey(status.Account, status.OrderRef);
    if(IsTerminalOrderStatus(status.OrderStatus))
    {
        m_OrderReferences.erase(key);
        return;
    }
    m_OrderReferences[key] = {
        status.Product,
        status.Ticker,
        status.ExchangeID,
        status.OrderToken,
        status.OrderType,
        status.OrderSide,
        status.SendPrice,
        status.SendVolume,
        status.TotalTradedVolume,
    };
}

bool ServerEngine::IsTerminalOrderStatus(uint8_t status)
{
    return status == Message::EOrderStatusType::EALLTRADED ||
           status == Message::EOrderStatusType::ECANCELLED ||
           status == Message::EOrderStatusType::EPARTTRADED_CANCELLED ||
           status == Message::EOrderStatusType::EBROKER_ERROR ||
           status == Message::EOrderStatusType::EEXCHANGE_ERROR;
}

std::string ServerEngine::OrderReferenceKey(const char* account, const char* orderRef)
{
    return std::string(account) + ":" + orderRef;
}

bool ServerEngine::ReloadPublishedPolicy()
{
    if(!m_RuntimePolicyClient)
    {
        return false;
    }
    RuntimePolicy next;
    std::string error;
    if(!m_RuntimePolicyClient->Fetch(next, error))
    {
        ++m_RuntimePolicyReloadFailures;
        // A transient control-plane outage must never clear the last accepted
        // policy. Log it explicitly so operations can distinguish a retained
        // policy from a process that stopped refreshing altogether.
        FMTLOG(fmtlog::WRN, "XServer published business policy reload failed, retaining current version, failures:{} error:{}",
               m_RuntimePolicyReloadFailures, error);
        return false;
    }
    m_RuntimePolicyReloadFailures = 0;
    const int nextVersion = next.Version();
    {
        std::unique_lock<std::shared_mutex> lock(m_RuntimePolicyMutex);
        if(m_RuntimePolicy && m_RuntimePolicy->Version() == nextVersion)
        {
            return true;
        }
        m_RuntimePolicy = std::make_shared<RuntimePolicy>(std::move(next));
    }
    FMTLOG(fmtlog::INF, "XServer activated published business policy version:{}", nextVersion);
    return true;
}

void ServerEngine::RunPublishedPolicyRefresh()
{
    const auto interval = std::chrono::seconds(m_XServerConfig.BusinessPolicyRefreshSeconds);
    FMTLOG(fmtlog::INF, "XServer published business policy refresh started, interval:{}s",
           m_XServerConfig.BusinessPolicyRefreshSeconds);
    while(true)
    {
        std::this_thread::sleep_for(interval);
        ReloadPublishedPolicy();
    }
}

void ServerEngine::SendAuthorizationError(HP_CONNID connection, const std::string& error) const
{
    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::EEventLog;
    message.EventLog.Level = Message::EEventLogLevel::EERROR;
    strncpy(message.EventLog.App, "XServer", sizeof(message.EventLog.App));
    strncpy(message.EventLog.Event, error.c_str(), sizeof(message.EventLog.Event));
    strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
    m_HPPackServer->SendData(connection, reinterpret_cast<const unsigned char*>(&message), sizeof(message));
}

void ServerEngine::SendOrderRejected(HP_CONNID connection, const Message::TOrderRequest& request,
                                     int errorID, const std::string& error) const
{
    // A policy or session rejection happens before XTrader can create an ATP
    // order reference. Return the original client token so vn.py can replace
    // its optimistic "submitting" row with a terminal rejected row.
    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::EOrderStatus;
    auto& status = message.OrderStatus;
    status.BusinessType = request.BusinessType;
    strncpy(status.Colo, request.Colo, sizeof(status.Colo));
    strncpy(status.Broker, request.Broker, sizeof(status.Broker));
    strncpy(status.Product, request.Product, sizeof(status.Product));
    strncpy(status.Account, request.Account, sizeof(status.Account));
    strncpy(status.Ticker, request.Ticker, sizeof(status.Ticker));
    strncpy(status.ExchangeID, request.ExchangeID, sizeof(status.ExchangeID));
    strncpy(status.RiskID, request.RiskID, sizeof(status.RiskID));
    strncpy(status.Trader, request.Trader, sizeof(status.Trader));
    strncpy(status.RecvMarketTime, request.RecvMarketTime, sizeof(status.RecvMarketTime));
    strncpy(status.SendTime, request.SendTime, sizeof(status.SendTime));
    status.OrderToken = request.OrderToken;
    status.EngineID = request.EngineID;
    status.UserReserved1 = request.UserReserved1;
    status.UserReserved2 = request.UserReserved2;
    status.OrderType = request.OrderType;
    status.OrderSide = request.Direction == Message::EOrderDirection::EBUY ?
        Message::EOrderSide::EOPEN_LONG : Message::EOrderSide::ECLOSE_LONG;
    status.OrderStatus = Message::EOrderStatusType::EBROKER_ERROR;
    status.SendPrice = request.Price;
    status.SendVolume = request.Volume;
    status.ErrorID = errorID;
    strncpy(status.ErrorMsg, error.c_str(), sizeof(status.ErrorMsg));
    strncpy(status.UpdateTime, Utils::getCurrentTimeUs(), sizeof(status.UpdateTime));
    m_HPPackServer->SendData(connection, reinterpret_cast<const unsigned char*>(&message), sizeof(message));
}

void ServerEngine::SendCancelRejected(HP_CONNID connection, const Message::TActionRequest& request,
                                      int errorID, const std::string& error) const
{
    const auto reference = m_OrderReferences.find(OrderReferenceKey(request.Account, request.OrderRef));
    if(reference == m_OrderReferences.end())
    {
        return;
    }
    // This is an active-order snapshot, not a terminal cancellation result.
    // vn.py can keep the order visible and allow a later retry.
    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::EOrderStatus;
    auto& status = message.OrderStatus;
    status.BusinessType = request.BusinessType;
    strncpy(status.Colo, request.Colo, sizeof(status.Colo));
    strncpy(status.Account, request.Account, sizeof(status.Account));
    strncpy(status.Product, reference->second.Product.c_str(), sizeof(status.Product));
    strncpy(status.Ticker, reference->second.Ticker.c_str(), sizeof(status.Ticker));
    strncpy(status.ExchangeID, reference->second.Exchange.c_str(), sizeof(status.ExchangeID));
    strncpy(status.OrderRef, request.OrderRef, sizeof(status.OrderRef));
    status.OrderToken = reference->second.OrderToken;
    status.OrderType = reference->second.OrderType;
    status.OrderSide = reference->second.OrderSide;
    status.OrderStatus = Message::EOrderStatusType::EEXCHANGE_ACK;
    status.SendPrice = reference->second.SendPrice;
    status.SendVolume = reference->second.SendVolume;
    status.TotalTradedVolume = reference->second.TotalTradedVolume;
    status.ErrorID = errorID;
    strncpy(status.ErrorMsg, error.c_str(), sizeof(status.ErrorMsg));
    strncpy(status.UpdateTime, Utils::getCurrentTimeUs(), sizeof(status.UpdateTime));
    m_HPPackServer->SendData(connection, reinterpret_cast<const unsigned char*>(&message), sizeof(message));
}

void ServerEngine::HandleRiskReport(const Message::PackMessage &msg)
{
    m_RiskReportHistoryQueue.push_back(msg);
    switch (msg.RiskReport.ReportType)
    {
        case Message::ERiskReportType::ERISK_TICKER_CANCELLED:
        {
            std::string Product = msg.RiskReport.Product;
            std::string Ticker = msg.RiskReport.Ticker;
            std::string Key = Product + ":" + Ticker;
            m_LastTickerCancelRiskReportMap[Key] = msg;
        }
        break;
        case Message::ERiskReportType::ERISK_ACCOUNT_LOCKED:
        {
            std::string Account = msg.RiskReport.Account;
            m_LastLockedAccountRiskReportMap[Account] = msg;
        }
        break;
        case Message::ERiskReportType::ERISK_LIMIT:
        {
            std::string RiskID = msg.RiskReport.RiskID;
            m_LastRiskLimitRiskReportMap[RiskID] = msg;
        }
        break;
        default:
            FMTLOG(fmtlog::WRN, "ServerEngine::HandleRiskReport unkown ReportType:{}", msg.RiskReport.ReportType);
            break;
    }

    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_RISKREPORT) != std::string::npos)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleRiskReport Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleColoStatus(const Message::PackMessage &msg)
{
    m_ColoStatusHistoryQueue.push_back(msg);
    std::string Colo = msg.ColoStatus.Colo;
    m_LastColoStatusMap[Colo] = msg;
    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_COLOSTATUS) != std::string::npos)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleColoStatus Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleAppStatus(const Message::PackMessage &msg)
{
    m_AppStatusHistoryQueue.push_back(msg);
    std::string Colo = msg.AppStatus.Colo;
    std::string AppName = msg.AppStatus.AppName;
    std::string Account = msg.AppStatus.Account;
    std::string Key = Colo + ":" + AppName + ":" + Account;
    m_LastAppStatusMap[Key] = msg;
    m_AppStatusMap[Key] = msg.AppStatus;
    // forward to monitor
    for (auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_APPSTATUS) != std::string::npos)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleAppStatus Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleFutureMarketData(const Message::PackMessage &msg)
{
    m_FutureMarketDataHistoryQueue.push_back(msg);
    // update last Future Market Data
    if(msg.FutureMarketData.Tick > -1)
    {
        m_LastFutureMarketDataMap[msg.FutureMarketData.Ticker] = msg;
    }
    // 仅转发给订阅 FutureMarket 的 XMonitor 连接，避免所有客户端承受行情流量。
    for(auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_FUTUREMARKET) != std::string::npos &&
            HasMarketSubscription(it->second.dwConnID, msg.FutureMarketData.Ticker, msg.FutureMarketData.ExchangeID))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleFutureMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
        else if (Message::EClientType::EXDATAPLAYER == it->second.ClientType)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleFutureMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleStockMarketData(const Message::PackMessage &msg)
{
    m_StockMarketDataHistoryQueue.push_back(msg);
    // update last Stock Market Data
    if(msg.StockMarketData.Tick > -1)
    {
        m_LastStockMarketDataMap[msg.StockMarketData.Ticker] = msg;
    }
    // forward to monitor
    for(auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if (Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_STOCKMARKET) != std::string::npos &&
            HasMarketSubscription(it->second.dwConnID, msg.StockMarketData.Ticker, msg.StockMarketData.ExchangeID))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleStockMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleSpotMarketData(const Message::PackMessage &msg)
{
    m_SpotMarketDataHistoryQueue.push_back(msg);
    // update last Stock Market Data
    if(msg.SpotMarketData.Tick > -1)
    {
        m_LastSpotMarketDataMap[msg.SpotMarketData.Ticker] = msg;
    }
    // forward to monitor
    for(auto it = m_HPPackServer->m_sConnections.begin(); it != m_HPPackServer->m_sConnections.end(); ++it)
    {
        std::string Messages = it->second.Messages;
        if(Message::EClientType::EXMONITOR == it->second.ClientType && Messages.find(MESSAGE_SPOTMARKET) != std::string::npos &&
           HasMarketSubscription(it->second.dwConnID, msg.SpotMarketData.Ticker, msg.SpotMarketData.ExchangeID))
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleSpotMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
        else if(Message::EClientType::EXWATCHER == it->second.ClientType)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleSpotMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
        else if (Message::EClientType::EXDATAPLAYER == it->second.ClientType)
        {
            m_HPPackServer->SendData(it->second.dwConnID, (const unsigned char *)&msg, sizeof(msg));
            FMTLOG(fmtlog::DBG, "ServerEngine::HandleSpotMarketData Send Data to Connection:{} successed, Account:{}, Messages:{}, MessgeType:{:#X}",
                    it->second.dwConnID, it->second.Account, Messages, msg.MessageType);
        }
    }
}

void ServerEngine::HandleSnapShotMessage(const Message::PackMessage &msg)
{
    unsigned int type = msg.MessageType;
    switch (type)
    {
    case Message::EMessageType::EEventLog:
        m_EventgLogHistoryQueue.push_back(msg);
        break;
    case Message::EMessageType::EAccountFund:
    {
        std::string Account = msg.AccountFund.Account;
        m_LastAccountFundMap[Account] = msg;
        m_AccountFundHistoryQueue.push_back(msg);
    }
    break;
    case Message::EMessageType::EAccountPosition:
    {
        std::string Account = msg.AccountPosition.Account;
        std::string Ticker = msg.AccountPosition.Ticker;
        std::string Key = Account + ":" + Ticker;
        m_LastAccountPostionMap[Key] = msg;
        m_AccountPositionHistoryQueue.push_back(msg);
    }
    break;
    case Message::EMessageType::EOrderStatus:
        m_OrderStatusHistoryQueue.push_back(msg);
        UpdateOrderReference(msg.OrderStatus);
        break;
    case Message::EMessageType::ERiskReport:
    {
        m_RiskReportHistoryQueue.push_back(msg);
        switch (msg.RiskReport.ReportType)
        {
            case Message::ERiskReportType::ERISK_TICKER_CANCELLED:
            {
                std::string Product = msg.RiskReport.Product;
                std::string Ticker = msg.RiskReport.Ticker;
                std::string Key = Product + ":" + Ticker;
                m_LastTickerCancelRiskReportMap[Key] = msg;
            }
            break;
            case Message::ERiskReportType::ERISK_ACCOUNT_LOCKED:
            {
                std::string Account = msg.RiskReport.Account;
                m_LastLockedAccountRiskReportMap[Account] = msg;
            }
            break;
            case Message::ERiskReportType::ERISK_LIMIT:
            {
                std::string RiskID = msg.RiskReport.RiskID;
                m_LastRiskLimitRiskReportMap[RiskID] = msg;
            }
            break;
        }
        break;
    }
    case Message::EMessageType::EColoStatus:
    {
        std::string Colo = msg.ColoStatus.Colo;
        m_LastColoStatusMap[Colo] = msg;
        m_ColoStatusHistoryQueue.push_back(msg);
        break;
    }
    case Message::EMessageType::EAppStatus:
    {
        std::string Colo = msg.AppStatus.Colo;
        std::string AppName = msg.AppStatus.AppName;
        std::string Account = msg.AppStatus.Account;
        std::string Key = Colo + ":" + AppName + ":" + Account;
        m_LastAppStatusMap[Key] = msg;
        m_AppStatusMap[Key] = msg.AppStatus;
        m_AppStatusHistoryQueue.push_back(msg);
        break;
    }
    case Message::EMessageType::EFutureMarketData:
    {
        m_FutureMarketDataHistoryQueue.push_back(msg);
        m_LastFutureMarketDataMap[msg.FutureMarketData.Ticker] = msg;
        break;
    }
    case Message::EMessageType::EStockMarketData:
    {
        m_StockMarketDataHistoryQueue.push_back(msg);
        m_LastStockMarketDataMap[msg.StockMarketData.Ticker] = msg;
        break;
    }
    case Message::EMessageType::ESpotMarketData:
    {
        m_SpotMarketDataHistoryQueue.push_back(msg);
        m_LastSpotMarketDataMap[msg.SpotMarketData.Ticker] = msg;
        break;
    }
    default:
        FMTLOG(fmtlog::WRN, "ServerEngine::HandleSnapShotMessage UnKown Message type:{:#X}", msg.MessageType);
        break;
    }
}

void ServerEngine::HistoryDataReplay()
{
    if(m_CurrentTimeStamp % 10000 == 0)
    {
        FMTLOG(fmtlog::INF, "ServerEngine::HistoryDataReplay FutureMarketData:{} StockMarketData:{} SpotMarketData:{} EventgLog:{} "
                            "OrderStatus:{} AccountFund:{} AccountPosition:{} RiskReport:{} ColoStatus:{} AppStatus:{}",
                m_FutureMarketDataHistoryQueue.size(), m_StockMarketDataHistoryQueue.size(), m_SpotMarketDataHistoryQueue.size(), m_EventgLogHistoryQueue.size(), 
                m_OrderStatusHistoryQueue.size(), m_AccountFundHistoryQueue.size(), m_AccountPositionHistoryQueue.size(), m_RiskReportHistoryQueue.size(), 
                m_ColoStatusHistoryQueue.size(), m_AppStatusHistoryQueue.size());
        usleep(1000);
    }
    // Trading Section
    if(IsTrading())
    {
        LastHistoryDataReplay();
        return;
    }
    if(m_CurrentTimeStamp % 5000 == 0 && m_HPPackServer->m_newConnections.size() > 0)
    {
        FMTLOG(fmtlog::INF, "ServerEngine::HistoryDataReplay History Data Replay Start FutureMarketData:{} StockMarketData:{} "
                            "SpotMarketData:{} EventgLog:{} OrderStatus:{} AccountFund:{} AccountPosition:{} RiskReport:{} ColoStatus:{} AppStatus:{}",
                m_FutureMarketDataHistoryQueue.size(), m_StockMarketDataHistoryQueue.size(), m_SpotMarketDataHistoryQueue.size(), m_EventgLogHistoryQueue.size(), 
                m_OrderStatusHistoryQueue.size(), m_AccountFundHistoryQueue.size(), m_AccountPositionHistoryQueue.size(), m_RiskReportHistoryQueue.size(), 
                m_ColoStatusHistoryQueue.size(), m_AppStatusHistoryQueue.size());
        unsigned int start = Utils::getTimeMs();
        long EventgLogCount = 0;
        long OrderStatusCount = 0;
        long FutureMarketDataCount = 0;
        long StockMarketDataCount = 0;
        long SpotMarketDataCount = 0;
        long RiskReportCount = 0;
        while (true)
        {
            static std::vector<InboundMessage> bufferQueue;
            InboundMessage inbound{};
            while(m_HPPackServer->m_PackMessageQueue.Pop(inbound))
            {
                if(inbound.Message.MessageType == Message::EMessageType::ELoginRequest)
                {
                    HandleLoginRequest(inbound.Message, inbound.ConnectionID);
                }
                else
                {
                    bufferQueue.push_back(inbound);
                }
            }
            // 非交易时段，可能造成消息乱序
            for(size_t i = 0; i < bufferQueue.size(); i++)
            {
                while(!m_HPPackServer->m_PackMessageQueue.Push(bufferQueue.at(i)));
            }
            bufferQueue.clear();

            if(0 == m_HPPackServer->m_newConnections.size())
                break;
            // EventLog Replay
            for (int i = EventgLogCount; i < m_EventgLogHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;
                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_EVENTLOG) != std::string::npos)
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_EventgLogHistoryQueue.at(i)),
                                             sizeof(m_EventgLogHistoryQueue.at(i)));
                    }
                }
                EventgLogCount++;
                usleep(2*1000);
                if(EventgLogCount % 100 == 0)
                    break;
            }
            // OrderStatus Replay
            for (int i = OrderStatusCount; i < m_OrderStatusHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;

                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_ORDERSTATUS) != std::string::npos &&
                        Authorize(it2->second.dwConnID, "account/" + Utils::ToString(m_OrderStatusHistoryQueue.at(i).OrderStatus.Account), "order:read"))
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_OrderStatusHistoryQueue.at(i)),
                                             sizeof(m_OrderStatusHistoryQueue.at(i)));
                    }
                }
                OrderStatusCount++;
                usleep(2*1000);
                if(OrderStatusCount % 100 == 0)
                    break;
            }

            // Future Market Data Replay
            for (int i = FutureMarketDataCount; FutureMarketDataCount < m_FutureMarketDataHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;

                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_FUTUREMARKET) != std::string::npos &&
                        HasMarketSubscription(it2->second.dwConnID, m_FutureMarketDataHistoryQueue.at(i).FutureMarketData.Ticker,
                                              m_FutureMarketDataHistoryQueue.at(i).FutureMarketData.ExchangeID))
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_FutureMarketDataHistoryQueue.at(i)),
                                             sizeof(m_FutureMarketDataHistoryQueue.at(i)));
                    }
                }
                FutureMarketDataCount++;
                usleep(2*1000);
                if(FutureMarketDataCount % 100 == 0)
                    break;
            }

            // Stock Market Data Replay
            for (int i = StockMarketDataCount; StockMarketDataCount < m_StockMarketDataHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;

                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_STOCKMARKET) != std::string::npos &&
                        HasMarketSubscription(it2->second.dwConnID, m_StockMarketDataHistoryQueue.at(i).StockMarketData.Ticker,
                                              m_StockMarketDataHistoryQueue.at(i).StockMarketData.ExchangeID))
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_StockMarketDataHistoryQueue.at(i)),
                                             sizeof(m_StockMarketDataHistoryQueue.at(i)));
                    }
                }
                StockMarketDataCount++;
                usleep(2*1000);
                if(StockMarketDataCount % 100 == 0)
                    break;
            }

            // Spot Market Data Replay
            for (int i = SpotMarketDataCount; SpotMarketDataCount < m_SpotMarketDataHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;

                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_SPOTMARKET) != std::string::npos &&
                        HasMarketSubscription(it2->second.dwConnID, m_SpotMarketDataHistoryQueue.at(i).SpotMarketData.Ticker,
                                              m_SpotMarketDataHistoryQueue.at(i).SpotMarketData.ExchangeID))
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_SpotMarketDataHistoryQueue.at(i)),
                                             sizeof(m_SpotMarketDataHistoryQueue.at(i)));
                    }
                }
                SpotMarketDataCount++;
                usleep(2*1000);
                if(SpotMarketDataCount % 100 == 0)
                    break;
            }

            // RiskReport Data Replay
            for (int i = RiskReportCount; RiskReportCount < m_RiskReportHistoryQueue.size(); i++)
            {
                if(m_HPPackServer->m_newConnections.size() == 0)
                    break;

                for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
                {
                    std::string Messages = it2->second.Messages;
                    if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_RISKREPORT) != std::string::npos)
                    {
                        m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_RiskReportHistoryQueue.at(i)),
                                             sizeof(m_RiskReportHistoryQueue.at(i)));
                    }
                }
                RiskReportCount++;
                usleep(2*1000);
                if(RiskReportCount % 100 == 0)
                    break;
            }

            if((0 == FutureMarketDataCount % 1000 || 0 == StockMarketDataCount % 1000 || 0 == SpotMarketDataCount % 1000) && 
                (FutureMarketDataCount <= m_FutureMarketDataHistoryQueue.size() || StockMarketDataCount <= m_StockMarketDataHistoryQueue.size() 
                || SpotMarketDataCount <= m_SpotMarketDataHistoryQueue.size()))
            {
                FMTLOG(fmtlog::INF, "ServerEngine::HistoryDataReplay History Data Replay FutureMarketData:{} StockMarketData:{} "
                                    "SpotMarketData:{} EventgLog:{} OrderStatus:{} RiskReport:{}",
                        FutureMarketDataCount, StockMarketDataCount, SpotMarketDataCount, EventgLogCount, OrderStatusCount, RiskReportCount);
            }
            // History Data Replay done
            if(FutureMarketDataCount >= m_FutureMarketDataHistoryQueue.size() && EventgLogCount >= m_EventgLogHistoryQueue.size()
                    && StockMarketDataCount >= m_StockMarketDataHistoryQueue.size() && OrderStatusCount >= m_OrderStatusHistoryQueue.size()
                    && RiskReportCount >= m_RiskReportHistoryQueue.size() && SpotMarketDataCount >= m_SpotMarketDataHistoryQueue.size())
            {
                for (auto it1 = m_HPPackServer->m_newConnections.begin(); it1 != m_HPPackServer->m_newConnections.end(); ++it1)
                {
                    std::string Messages = it1->second.Messages;
                    // Account Fund Data Replay
                    if (Message::EClientType::EXMONITOR == it1->second.ClientType && Messages.find(MESSAGE_ACCOUNTFUND) != std::string::npos)
                    {
                        for (auto it2 = m_LastAccountFundMap.begin(); it2 != m_LastAccountFundMap.end(); it2++)
                        {
                            if(Authorize(it1->second.dwConnID, "account/" + Utils::ToString(it2->second.AccountFund.Account), "account:read"))
                            {
                                m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char *)&(it2->second), sizeof(it2->second));
                            }
                        }
                    }
                    // Account Position Data Replay
                    if (Message::EClientType::EXMONITOR == it1->second.ClientType && Messages.find(MESSAGE_ACCOUNTPOSITION) != std::string::npos)
                    {
                        
                        for (auto it2 = m_LastAccountPostionMap.begin(); it2 != m_LastAccountPostionMap.end(); it2++)
                        {
                            if(Authorize(it1->second.dwConnID, "account/" + Utils::ToString(it2->second.AccountPosition.Account), "account:read"))
                            {
                                m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char *)&(it2->second), sizeof(it2->second));
                            }
                        }
                    }
                    // // ColoStatus Data Replay
                    if (Message::EClientType::EXMONITOR == it1->second.ClientType && Messages.find(MESSAGE_COLOSTATUS) != std::string::npos)
                    {
                        
                        for (auto it2 = m_LastColoStatusMap.begin(); it2 != m_LastColoStatusMap.end(); it2++)
                        {
                            m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char *)&(it2->second), sizeof(it2->second));
                        }
                    }
                    // // AppStatus Data Replay
                    if (Message::EClientType::EXMONITOR == it1->second.ClientType && Messages.find(MESSAGE_APPSTATUS) != std::string::npos)
                    {
                        
                        for (auto it2 = m_LastAppStatusMap.begin(); it2 != m_LastAppStatusMap.end(); it2++)
                        {
                            m_HPPackServer->SendData(it1->second.dwConnID, (const unsigned char *)&(it2->second), sizeof(it2->second));
                        }
                    }
                }
                break;
            }
        }
        unsigned int end = Utils::getTimeMs();
        double elapsed = (end - start) / 1000.0;
        FMTLOG(fmtlog::INF, "ServerEngine::HistoryDataReplay History Data Replay End, connections:{}, Replay FutureMarketData:{} "
                            "StockMarketData:{} EventgLog:{} OrderStatus:{}, elapsed:{}s",
                m_HPPackServer->m_newConnections.size(), FutureMarketDataCount, StockMarketDataCount, EventgLogCount, OrderStatusCount, elapsed);
        // clear
        m_HPPackServer->m_newConnections.clear();
    }
}

void ServerEngine::LastHistoryDataReplay()
{
    // EventLog Replay
    for (int i = 0; i < m_EventgLogHistoryQueue.size(); i++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_EVENTLOG) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(m_EventgLogHistoryQueue.at(i)), sizeof(m_EventgLogHistoryQueue.at(i)));
            }
        }
    }
    
    // AccountFund Replay
    for (auto it1 = m_LastAccountFundMap.begin(); it1 != m_LastAccountFundMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_ACCOUNTFUND) != std::string::npos &&
                Authorize(it2->second.dwConnID, "account/" + Utils::ToString(it1->second.AccountFund.Account), "account:read"))
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }
    // AccountPosition Replay
    for (auto it1 = m_LastAccountPostionMap.begin(); it1 != m_LastAccountPostionMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_ACCOUNTPOSITION) != std::string::npos &&
                Authorize(it2->second.dwConnID, "account/" + Utils::ToString(it1->second.AccountPosition.Account), "account:read"))
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }
    // Market Data Replay
    for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
    {
        std::string Messages = it2->second.Messages;
        if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_FUTUREMARKET) != std::string::npos)
        {
            for(auto it3 = m_LastFutureMarketDataMap.begin(); it3 != m_LastFutureMarketDataMap.end(); it3++)
            {
                if(HasMarketSubscription(it2->second.dwConnID, it3->second.FutureMarketData.Ticker,
                                         it3->second.FutureMarketData.ExchangeID))
                {
                    m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&it3->second, sizeof(it3->second));
                }
            }
        }

        if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_STOCKMARKET) != std::string::npos)
        {
            for(auto it3 = m_LastStockMarketDataMap.begin(); it3 != m_LastStockMarketDataMap.end(); it3++)
            {
                if(HasMarketSubscription(it2->second.dwConnID, it3->second.StockMarketData.Ticker,
                                         it3->second.StockMarketData.ExchangeID))
                {
                    m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&it3->second, sizeof(it3->second));
                }
            }
        }
    }
    // OrderStatus Replay
    for (auto it1 = m_OrderStatusHistoryQueue.begin(); it1 != m_OrderStatusHistoryQueue.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_ORDERSTATUS) != std::string::npos &&
                Authorize(it2->second.dwConnID, "account/" + Utils::ToString(it1->OrderStatus.Account), "order:read"))
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(*it1), sizeof(*it1));
            }
        }
    }
    // RiskReport
    for (auto it1 = m_LastTickerCancelRiskReportMap.begin(); it1 != m_LastTickerCancelRiskReportMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_RISKREPORT) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }
    for (auto it1 = m_LastLockedAccountRiskReportMap.begin(); it1 != m_LastLockedAccountRiskReportMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_RISKREPORT) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }
    for (auto it1 = m_LastRiskLimitRiskReportMap.begin(); it1 != m_LastRiskLimitRiskReportMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_RISKREPORT) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }

    // ColoStatus Replay
    for (auto it1 = m_LastColoStatusMap.begin(); it1 != m_LastColoStatusMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_COLOSTATUS) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }

    // AppStatus Replay
    for (auto it1 = m_LastAppStatusMap.begin(); it1 != m_LastAppStatusMap.end(); it1++)
    {
        if(m_HPPackServer->m_newConnections.size() == 0)
            break;
        for (auto it2 = m_HPPackServer->m_newConnections.begin(); it2 != m_HPPackServer->m_newConnections.end(); ++it2)
        {
            std::string Messages = it2->second.Messages;
            if (Message::EClientType::EXMONITOR == it2->second.ClientType && Messages.find(MESSAGE_APPSTATUS) != std::string::npos)
            {
                m_HPPackServer->SendData(it2->second.dwConnID, (const unsigned char *)&(it1->second), sizeof(it1->second));
            }
        }
    }
    m_HPPackServer->m_newConnections.clear();
}

void ServerEngine::UpdateUserPermissionTable(const Message::PackMessage &msg)
{
    std::string sql, op;
    Message::TLoginResponse rsp;
    FMTLOG(fmtlog::INF, "XRiskEngine::ParseUpdateUserPermissionCommand start size:{} {}", m_UserPermissionMap.size(), msg.Command.Command);
    if(ParseUpdateUserPermissionCommand(msg.Command.Command, sql, op, rsp))
    {
        std::string errorString;
        bool ok = m_UserDBManager->UpdateUserPermissionTable(sql, op, &ServerEngine::sqlite3_callback_UserPermission, errorString);
        if(ok)
        {
            if(Utils::equalWith(op, "INSERT"))
            {
                rsp.Operation = Message::EPermissionOperation::EUSER_ADD;
            }
            else if(Utils::equalWith(op, "UPDATE"))
            {
                rsp.Operation = Message::EPermissionOperation::EUSER_UPDATE;
            }
            else if(Utils::equalWith(op, "DELETE"))
            {
                rsp.Operation = Message::EPermissionOperation::EUSER_DELETE;
            }
            auto it = m_UserPermissionMap.find(rsp.Account);
            if(m_UserPermissionMap.end() == it)
            {
                m_UserPermissionMap.insert(std::pair<std::string, Message::TLoginResponse>(rsp.Account, rsp));
            }
            else
            {
                it->second.Operation = rsp.Operation;
            }
            QueryUserPermission();
            if(Message::EPermissionOperation::EUSER_DELETE == rsp.Operation)
            {
                m_UserPermissionMap.erase(rsp.Account);
            }
        }
        else
        {
            FMTLOG(fmtlog::WRN, "XRiskEngine::ParseUpdateUserPermissionCommand failed:{}", errorString);
        }
        FMTLOG(fmtlog::INF, "XRiskEngine::ParseUpdateUserPermissionCommand end size:{}", m_UserPermissionMap.size());
    }
}

bool ServerEngine::ParseUpdateUserPermissionCommand(const std::string& cmd, std::string& sql, std::string& op, Message::TLoginResponse& rsp)
{
    bool ret = true;
    sql.clear();
    std::vector<std::string> items;
    Utils::Split(cmd, ",", items);
    if(6 == items.size())
    {
        std::vector<std::string> keyValue;
        Utils::Split(items[0], ":", keyValue);
        std::string UserName = keyValue[1];
        strncpy(rsp.Account, UserName.c_str(), sizeof(rsp.Account));

        keyValue.clear();
        Utils::Split(items[1], ":", keyValue);
        std::string PassWord = keyValue[1];
        strncpy(rsp.PassWord, PassWord.c_str(), sizeof(rsp.PassWord));

        keyValue.clear();
        Utils::Split(items[2], ":", keyValue);
        std::string Operation = keyValue[1];

        keyValue.clear();
        Utils::Split(items[3], ":", keyValue);
        std::string Role = keyValue[1];
        strncpy(rsp.Role, Role.c_str(), sizeof(rsp.Role));

        keyValue.clear();
        Utils::Split(items[4], ":", keyValue);
        std::string Plugins = keyValue[1];
        strncpy(rsp.Plugins, Plugins.c_str(), sizeof(rsp.Plugins));

        keyValue.clear();
        Utils::Split(items[5], ":", keyValue);
        std::string Messages = keyValue[1];
        strncpy(rsp.Messages, Messages.c_str(), sizeof(rsp.Messages));

        std::string CurrentTime = Utils::getCurrentTimeUs();
        strncpy(rsp.UpdateTime, CurrentTime.c_str(), sizeof(rsp.UpdateTime));
        char buffer[1024] = {0};
        auto it = m_UserPermissionMap.find(UserName);
        if(m_UserPermissionMap.end() == it)
        {
            sprintf(buffer, "INSERT INTO UserPermissionTable(UserName,PassWord,Role,Plugins,Messages,UpdateTime) VALUES ('%s', '%s', '%s', '%s', '%s', '%s');",
                    UserName.c_str(), PassWord.c_str(), Role.c_str(), Plugins.c_str(), Messages.c_str(), CurrentTime.c_str());
            op = "INSERT";
        }
        else
        {
            // Update
            if(Utils::equalWith(Operation, "Add") || Utils::equalWith(Operation, "Update"))
            {
                sprintf(buffer, "UPDATE UserPermissionTable SET PassWord='%s',Role='%s',Plugins='%s',Messages='%s',UpdateTime='%s' WHERE UserName='%s';",
                        PassWord.c_str(), Role.c_str(), Plugins.c_str(), Messages.c_str(), CurrentTime.c_str(), UserName.c_str());
                op = "UPDATE";
            }
            else if(Utils::equalWith(Operation, "Delete"))
            {
                sprintf(buffer, "DELETE FROM UserPermissionTable WHERE UserName='%s';", UserName.c_str());
                op = "DELETE";
            }
        }
        sql = buffer;
        FMTLOG(fmtlog::INF, "ServerEngine::ParseUpdateUserPermissionCommand successed, UserName:{} Role:{} Plugins:{} Messages:{} MapSize:{}",
                UserName, Role, Plugins, Messages, m_UserPermissionMap.size());
    }
    else
    {
        ret = false;
        sprintf(rsp.ErrorMsg, "invalid command: %s", cmd.c_str());
        FMTLOG(fmtlog::WRN, "ServerEngine::ParseUpdateUserPermissionCommand invalid command, {}", cmd);
    }

    return ret;
}

int ServerEngine::sqlite3_callback_UserPermission(void *data, int argc, char **argv, char **azColName)
{
    for(int i = 0; i < argc; i++)
    {
        std::string colName = azColName[i];
        std::string value = argv[i];
        // The local compatibility table still contains a password field. Do
        // not emit it to files or clients while loading the permission cache.
        if(colName == "PassWord")
        {
            FMTLOG(fmtlog::INF, "ServerEngine::sqlite3_callback_UserPermission, {} {} = [redacted]",
                   (char*)data, azColName[i]);
        }
        else
        {
            FMTLOG(fmtlog::INF, "ServerEngine::sqlite3_callback_UserPermission, {} {} = {}",
                   (char*)data, azColName[i], argv[i]);
        }
        static std::string UserName;
        static std::string PassWord;
        static std::string Role;
        static std::string Plugins;
        static std::string Messages;
        static std::string UpdateTime;

        if(Utils::equalWith(colName, "UserName"))
        {
            UserName = value;
        }
        if(Utils::equalWith(colName, "PassWord"))
        {
            PassWord = value.c_str();
        }
        if(Utils::equalWith(colName, "Role"))
        {
            Role = value.c_str();
        }
        if(Utils::equalWith(colName, "Plugins"))
        {
            Plugins = value.c_str();
        }
        if(Utils::equalWith(colName, "Messages"))
        {
            Messages = value.c_str();
        }
        if(Utils::equalWith(colName, "UpdateTime"))
        {
            std::string UpdateTime = value;
            Message::TLoginResponse& rsp = m_UserPermissionMap[UserName];
            strncpy(rsp.Account, UserName.c_str(), sizeof(rsp.Account));
            strncpy(rsp.PassWord, PassWord.c_str(), sizeof(rsp.PassWord));
            strncpy(rsp.Role, Role.c_str(), sizeof(rsp.Role));
            strncpy(rsp.Plugins, Plugins.c_str(), sizeof(rsp.Plugins));
            strncpy(rsp.Messages, Messages.c_str(), sizeof(rsp.Messages));
            rsp.Operation = Message::EPermissionOperation::EUSER_UPDATE;
            strncpy(rsp.UpdateTime, UpdateTime.c_str(), sizeof(rsp.UpdateTime));
        }
    }
    return 0;
}

bool ServerEngine::QueryUserPermission()
{
    std::string errorString;
    bool ret = m_UserDBManager->QueryUserPermission(&ServerEngine::sqlite3_callback_UserPermission, errorString);
    if(!ret)
    {
        FMTLOG(fmtlog::WRN, "ServerEngine::QueryUserPermission failed, {}", errorString);
    }
    else
    {
        for (auto it1 = m_HPPackServer->m_sConnections.begin(); it1 != m_HPPackServer->m_sConnections.end(); ++it1)
        {
            if (Message::EClientType::EXMONITOR == it1->second.ClientType &&
                    (Utils::equalWith(it1->second.Account, "root") || Utils::equalWith(it1->second.Account, "admin")))
            {
                for (auto it2 = m_UserPermissionMap.begin(); it2 != m_UserPermissionMap.end(); it2++)
                {
                    Message::PackMessage message;
                    memset(&message, 0, sizeof(message));
                    message.MessageType = Message::EMessageType::ELoginResponse;
                    memcpy(&message.LoginResponse, &it2->second, sizeof(message.LoginResponse));
                    m_HPPackServer->SendData(it1->second.dwConnID,
                                         (const unsigned char *)&message, sizeof(message));
                }
            }
        }
    }
    return ret;
}

void ServerEngine::UpdateAppStatusTable()
{
    static bool ok = false;
    if(!ok && m_CurrentTimeStamp / 1000 == m_AppStatusStoreTime / 1000)
    {
        FMTLOG(fmtlog::INF, "ServerEngine::UpdateAppStatusTable, App:{}", m_AppStatusMap.size());
        std::string errorString;
        m_UserDBManager->UpdateAppStatusTable("DELETE FROM AppStatusTable;", "DELETE", &ServerEngine::sqlite3_callback_AppStatus, errorString);
        for(auto it = m_AppStatusMap.begin(); it != m_AppStatusMap.end(); it++)
        {
            std::string Status = it->second.Status;
            // 收盘后进程状态为NoStart的进程App不进行存储
            if(Status != "NoStart")
            {
                char sql[256] = {0};
                sprintf(sql, "INSERT INTO AppStatusTable(Colo, AppName, Account, PID, Status, UpdateTime) VALUES ('%s', '%s', '%s', '%d', '%s', '%s');", 
                    it->second.Colo, it->second.AppName, it->second.Account, it->second.PID, it->second.Status, Utils::getCurrentTimeUs());
                m_UserDBManager->UpdateAppStatusTable(sql, "INSERT", &ServerEngine::sqlite3_callback_AppStatus, errorString);
            }
        }
        ok = true;
    }
}

int ServerEngine::sqlite3_callback_AppStatus(void *data, int argc, char **argv, char **azColName)
{
    for(int i = 0; i < argc; i++)
    {
        FMTLOG(fmtlog::INF, "ServerEngine::sqlite3_callback_AppStatus, {} {} = {}", (char*)data, azColName[i], argv[i]);
        std::string colName = azColName[i];
        std::string value = argv[i];
        static std::string Colo;
        static std::string AppName;
        static std::string Account;
        static std::string PID;
        static std::string Status;

        if(Utils::equalWith(colName, "Colo"))
        {
            Colo = value;
        }
        if(Utils::equalWith(colName, "AppName"))
        {
            AppName = value;
        }
        if(Utils::equalWith(colName, "Account"))
        {
            Account = value;
        }
        if(Utils::equalWith(colName, "PID"))
        {
            PID = value;
        }
        if(Utils::equalWith(colName, "Status"))
        {
            Status = value;
            std::string Key = Colo + ":" + AppName + ":" + Account;
            Message::TAppStatus& AppStatus = m_AppStatusMap[Key];
            strncpy(AppStatus.Colo, Colo.c_str(), sizeof(AppStatus.Account));
            strncpy(AppStatus.AppName, AppName.c_str(), sizeof(AppStatus.AppName));
            strncpy(AppStatus.Account, Account.c_str(), sizeof(AppStatus.Account));
            AppStatus.PID = atoi(PID.c_str());
            strncpy(AppStatus.Status, "NoStart", sizeof(AppStatus.Status));
        }
    }
    return 0;
}

void ServerEngine::CheckAppStatus()
{
    static bool ok = false;
    if(!ok && m_CurrentTimeStamp/1000 == m_AppCheckTime/1000)
    {
        FMTLOG(fmtlog::INF, "ServerEngine::CheckAppStatus, App:{}", m_AppStatusMap.size());
        for(auto it = m_AppStatusMap.begin(); it != m_AppStatusMap.end(); it++)
        {
            if(Utils::equalWith(it->second.Status, "NoStart"))
            {
                char errorString[256] = {0};
                sprintf(errorString, "Colo: %s AppName: %s Account: %s NoStart", it->second.Colo, it->second.AppName, it->second.Account);
                Message::PackMessage message;
                memset(&message, 0, sizeof(message));
                message.MessageType = Message::EMessageType::EEventLog;
                message.EventLog.Level = Message::EEventLogLevel::EWARNING;
                strncpy(message.EventLog.Colo, it->second.Colo, sizeof(message.EventLog.Colo));
                strncpy(message.EventLog.App, it->second.AppName, sizeof(message.EventLog.App));
                strncpy(message.EventLog.Account, it->second.Account, sizeof(message.EventLog.Account));
                strncpy(message.EventLog.Event, errorString, sizeof(message.EventLog.Event));
                strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
                HandleEventLog(message);
                FMTLOG(fmtlog::WRN, "Colo: {} AppName: {} Account: {} NoStart", it->second.Colo, it->second.AppName, it->second.Account);
            }
        }
        ok = true;
    }
}

bool ServerEngine::IsTrading()const
{
    return m_Trading;
}

void ServerEngine::CheckTrading()
{
    std::string buffer = Utils::getCurrentTimeMs() + 11;
    m_CurrentTimeStamp = Utils::getTimeStampMs(buffer.c_str());
    m_Trading  = (m_CurrentTimeStamp >= m_OpenTime && m_CurrentTimeStamp <= m_CloseTime);
}
