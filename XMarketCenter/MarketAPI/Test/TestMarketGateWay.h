#ifndef TESTMARKETGATEWAY_H
#define TESTMARKETGATEWAY_H

#include <mutex>
#include <unordered_map>

#include "MarketGateWay.hpp"


class TestMarketGateWay : public MarketGateWay
{
public:
    explicit TestMarketGateWay();
    virtual ~TestMarketGateWay();
public:
    virtual bool LoadAPIConfig();
    virtual void Run();
    virtual void HandleCommand(const Message::TCommand& command);
    virtual void GetCommitID(std::string& CommitID, std::string& UtilsCommitID);
    virtual void GetAPIVersion(std::string& APIVersion);
protected:
    std::vector<Utils::TickerProperty> GetActiveTickers();
    void AddActiveTicker(const Utils::TickerProperty& ticker);

    // test 模式必须和桌面股票工作台使用相同的消息类型；否则即使服务在线，
    // XServer 也不会把 CFFEX 期货行情投递给订阅 SZSE/SSE 的客户端。
    MarketData::TStockMarketData m_MarketData;
    std::mutex m_ActiveTickerMutex;
    std::unordered_map<std::string, Utils::TickerProperty> m_ActiveTickerMap;
};

#endif // TESTMARKETGATEWAY_H
