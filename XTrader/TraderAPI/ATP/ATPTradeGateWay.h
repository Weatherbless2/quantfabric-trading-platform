#ifndef ATPTRADEGATEWAY_H
#define ATPTRADEGATEWAY_H

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include "StockTradeGateWay.hpp"

class ATPTradeGateWay : public StockTradeGateWay
{
public:
    explicit ATPTradeGateWay();
    virtual ~ATPTradeGateWay();

    virtual void LoadAPIConfig();
    virtual void GetCommitID(std::string& CommitID, std::string& UtilsCommitID);
    virtual void GetAPIVersion(std::string& APIVersion);
    virtual void CreateTraderAPI();
    virtual void DestroyTraderAPI();
    virtual void ReqUserLogin();
    virtual void LoadTrader();
    virtual void ReLoadTrader();
    virtual int ReqQryFund();
    virtual int ReqQryPoistion();
    virtual int ReqQryTrade();
    virtual int ReqQryOrder();
    virtual int ReqQryTickerRate();
    virtual void ReqInsertOrder(const Message::TOrderRequest& request);
    virtual void ReqInsertOrderRejected(const Message::TOrderRequest& request);
    virtual void ReqCancelOrder(const Message::TActionRequest& request);
    virtual void ReqCancelOrderRejected(const Message::TActionRequest& request);
    virtual void RepayMarginDirect(double value);
    virtual void TransferFundIn(double value);
    virtual void TransferFundOut(double value);

private:
    int ConnectBridge();
    bool SendLine(const std::string& line);
    int SendQuery(const char *name);
    void ReceiveLoop();
    void HandleMessage(const std::string& line);
    void PublishRejected(const Message::TOrderRequest& request, int errorID, const char *errorMsg);
    void PublishCancelFailure(const std::string& orderRef, int errorID, const std::string& errorMsg);
    void RequestAccountStateRecovery();

    std::string m_BridgeHost;
    int m_BridgePort;
    bool m_EnableOrders;
    int m_Socket;
    std::atomic<bool> m_Stop;
    std::thread m_ReceiveThread;
    std::mutex m_SocketMutex;
    std::mutex m_CancelStateMutex;
    std::unordered_set<uint64_t> m_SubmittedOrderTokens;
    std::unordered_map<std::string, Message::TOrderStatus> m_PreCancelOrderStatusMap;
};

#endif // ATPTRADEGATEWAY_H
