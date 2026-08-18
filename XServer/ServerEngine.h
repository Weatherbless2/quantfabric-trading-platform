#ifndef SERVERENGINE_H
#define SERVERENGINE_H

#include <list>
#include <vector>
#include <mutex>
#include <shared_mutex>
#include <stdlib.h>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <memory>
#include "AuthzClient.hpp"
#include "RuntimePolicy.hpp"
#include "HPPackServer.h"
#include "YMLConfig.hpp"
#include "UserDBManager.hpp"
#include "SnapShotHelper.hpp"

class ServerEngine
{
public:
    explicit ServerEngine();
    void LoadConfig(const char* yml);
    void Run();
protected:
    void RegisterServer(const char *ip, unsigned int port);
    void WorkFunc();
    void HandlePackMessage(const InboundMessage& inbound);
    void HandleLoginRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection);
    void HandleCommand(const Message::PackMessage &msg, HP_CONNID sourceConnection);
    void HandleEventLog(const Message::PackMessage &msg);
    void HandleAccountFund(const Message::PackMessage &msg);
    void HandleAccountPosition(const Message::PackMessage &msg);
    void HandleOrderStatus(const Message::PackMessage &msg);
    void HandleOrderRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection);
    void HandleActionRequest(const Message::PackMessage &msg, HP_CONNID sourceConnection);
    void HandleRiskReport(const Message::PackMessage &msg);
    void HandleColoStatus(const Message::PackMessage &msg);
    void HandleAppStatus(const Message::PackMessage &msg);
    void HandleFutureMarketData(const Message::PackMessage &msg);
    void HandleStockMarketData(const Message::PackMessage &msg);
    void HandleSpotMarketData(const Message::PackMessage &msg);

    void HandleSnapShotMessage(const Message::PackMessage &msg);
    void HistoryDataReplay();
    void LastHistoryDataReplay();

    void UpdateUserPermissionTable(const Message::PackMessage &msg);
    bool ParseUpdateUserPermissionCommand(const std::string& cmd, std::string& sql, std::string& op, Message::TLoginResponse& rsp);
    static int sqlite3_callback_UserPermission(void *data, int argc, char **argv, char **azColName);
    bool QueryUserPermission();

    void UpdateAppStatusTable();
    static int sqlite3_callback_AppStatus(void *data, int argc, char **argv, char **azColName);
    void CheckAppStatus();

    bool IsTrading()const;
    void CheckTrading();
    bool Authorize(HP_CONNID sourceConnection, const std::string& resource,
                   const std::string& action, const std::string& traceID = "");
    bool HasMarketSubscription(HP_CONNID connection, const std::string& ticker,
                               const std::string& exchange) const;
    bool AuthorizePublishedPolicyForSubscription(const std::string& ticker, const std::string& exchange,
                                                 std::string& error) const;
    bool AuthorizePublishedPolicyForOrder(const Message::TOrderRequest& request,
                                          std::string& error) const;
    bool AuthorizePublishedPolicyForCancel(const Message::TActionRequest& request,
                                           std::string& error) const;
    void UpdateOrderReference(const Message::TOrderStatus& status);
    static bool IsTerminalOrderStatus(uint8_t status);
    static std::string OrderReferenceKey(const char* account, const char* orderRef);
    bool ReloadPublishedPolicy();
    void RunPublishedPolicyRefresh();
    void SendAuthorizationError(HP_CONNID connection, const std::string& message) const;
    void SendOrderRejected(HP_CONNID connection, const Message::TOrderRequest& request,
                           int errorID, const std::string& message) const;
    void SendCancelRejected(HP_CONNID connection, const Message::TActionRequest& request,
                            int errorID, const std::string& message) const;
private:
    HPPackServer* m_HPPackServer;
    Message::PackMessage m_PackMessage;
    Utils::XServerConfig m_XServerConfig;
    bool m_Trading;
    unsigned long m_CurrentTimeStamp;
    int m_OpenTime;
    int m_CloseTime;
    int m_AppCheckTime;
    int m_AppStatusStoreTime;
    std::thread* m_WorkThread;
    static std::unordered_map<std::string, Message::TLoginResponse> m_UserPermissionMap;
    UserDBManager* m_UserDBManager;
    static std::unordered_map<std::string, Message::TAppStatus> m_AppStatusMap;
    std::vector<Message::PackMessage> m_FutureMarketDataHistoryQueue;
    std::vector<Message::PackMessage> m_StockMarketDataHistoryQueue;
    std::vector<Message::PackMessage> m_SpotMarketDataHistoryQueue;
    std::vector<Message::PackMessage> m_EventgLogHistoryQueue;
    std::vector<Message::PackMessage> m_OrderStatusHistoryQueue;
    std::vector<Message::PackMessage> m_RiskReportHistoryQueue;
    std::vector<Message::PackMessage> m_AccountFundHistoryQueue;
    std::vector<Message::PackMessage> m_AccountPositionHistoryQueue;
    std::vector<Message::PackMessage> m_ColoStatusHistoryQueue;
    std::vector<Message::PackMessage> m_AppStatusHistoryQueue;
    std::unordered_map<std::string, Message::PackMessage> m_LastAccountPostionMap; // Account + ":" + Ticker, AccountPostion
    std::unordered_map<std::string, Message::PackMessage> m_LastAccountFundMap;// Account, AccountFund
    std::unordered_map<std::string, Message::PackMessage> m_LastTickerCancelRiskReportMap;// Product + ":" + Ticker, RiskReport
    std::unordered_map<std::string, Message::PackMessage> m_LastLockedAccountRiskReportMap; // Account, RiskReport
    std::unordered_map<std::string, Message::PackMessage> m_LastRiskLimitRiskReportMap;// RiskID, RiskReport
    std::unordered_map<std::string, Message::PackMessage> m_LastColoStatusMap; // Colo, ColoStatus
    std::unordered_map<std::string, Message::PackMessage> m_LastAppStatusMap;// Colo + ":" + AppName + ":" + Account, AppStatus
    std::unordered_map<std::string, Message::PackMessage> m_LastFutureMarketDataMap;// Ticker, FutureMarketData
    std::unordered_map<std::string, Message::PackMessage> m_LastStockMarketDataMap;// Ticker, StockMarketData
    std::unordered_map<std::string, Message::PackMessage> m_LastSpotMarketDataMap;// Ticker, SpotMarketData
    std::string m_SnapShotPath;
    std::unique_ptr<AuthzClient> m_AuthzClient;
    std::unique_ptr<RuntimePolicyClient> m_RuntimePolicyClient;
    std::shared_ptr<const RuntimePolicy> m_RuntimePolicy;
    mutable std::shared_mutex m_RuntimePolicyMutex;
    std::thread* m_RuntimePolicyRefreshThread = nullptr;
    unsigned int m_RuntimePolicyReloadFailures = 0;
    std::unordered_map<HP_CONNID, std::unordered_set<std::string>> m_MarketSubscriptions;
    struct OrderReferenceContext
    {
        std::string Product;
        std::string Ticker;
        std::string Exchange;
        int OrderToken = 0;
        uint8_t OrderType = Message::EOrderType::ELIMIT;
        uint8_t OrderSide = Message::EOrderSide::EOPEN_LONG;
        double SendPrice = 0;
        unsigned int SendVolume = 0;
        unsigned int TotalTradedVolume = 0;
    };
    // TActionRequest carries only Account and OrderRef. This context is built
    // from exchange order reports so cancellation can enforce security rules.
    std::unordered_map<std::string, OrderReferenceContext> m_OrderReferences;
};

#endif // SERVERENGINE_H
