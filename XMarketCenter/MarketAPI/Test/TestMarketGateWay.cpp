#include "TestMarketGateWay.h"
#include "XPluginEngine.hpp"

#include <algorithm>
#include <cctype>
#include <ctime>

CreateObjectFunc(TestMarketGateWay);

namespace
{
bool IsStockSubscription(const std::string& ticker, const std::string& exchange)
{
    return ticker.size() == 6 &&
           std::all_of(ticker.begin(), ticker.end(), [](unsigned char value) { return std::isdigit(value); }) &&
           (exchange == "SSE" || exchange == "SZSE");
}

std::string TickerKey(const Utils::TickerProperty& ticker)
{
    return ticker.Ticker + "." + ticker.ExchangeID;
}

int PriceSeed(const std::string& ticker)
{
    return std::stoi(ticker) % 3000;
}
}

TestMarketGateWay::TestMarketGateWay() : MarketGateWay()
{

}

TestMarketGateWay::~TestMarketGateWay()
{

}

bool TestMarketGateWay::LoadAPIConfig()
{
    m_Logger->Log->info("TestMarketGateWay::LoadAPIConfig");
    // Load API Config

    return true;
}

void TestMarketGateWay::Run()
{
    for(const Utils::TickerProperty& ticker : m_TickerPropertyList)
    {
        AddActiveTicker(ticker);
    }
    m_Logger->Log->info("TestMarketGateWay::Run Start A-share test market gateway, tickers:{}",
                        GetActiveTickers().size());
    while(true)
    {
        static int tick = 0;
        ++tick;
        const time_t now = time(NULL);
        struct tm localTime;
        localtime_r(&now, &localTime);
        char updateTime[sizeof(m_MarketData.UpdateTime)] = {0};
        strftime(updateTime, sizeof(updateTime), "%H:%M:%S", &localTime);

        // 配置中的基础标的保证 XQuant 有稳定输入；桌面端新增订阅的股票由
        // XServer -> XWatcher -> XMarketCenter 转入活跃集合，避免为 5,212 只
        // 证券无差别生成测试 Tick。
        const std::vector<Utils::TickerProperty> activeTickers = GetActiveTickers();
        for(const Utils::TickerProperty& tickerProperty : activeTickers)
        {
            const double priceTick = tickerProperty.PriceTick > 0 ? tickerProperty.PriceTick : 0.01;
            const int priceSeed = PriceSeed(tickerProperty.Ticker);
            const double preClose = 8.0 + static_cast<double>(priceSeed) / 100.0;
            // 先使用有符号整数计算涨跌步数，避免减去 10 时发生无符号下溢，
            // 进而把模拟价格放大为接近 double 最大值的无效报价。
            const int movement = (tick + priceSeed) % 21 - 10;
            const double lastPrice = preClose + static_cast<double>(movement) * priceTick;

            memset(&m_MarketData, 0, sizeof(m_MarketData));
            m_MarketData.LastTick = tick - 1;
            m_MarketData.Tick = tick;
            strncpy(m_MarketData.Ticker, tickerProperty.Ticker.c_str(), sizeof(m_MarketData.Ticker));
            strncpy(m_MarketData.ExchangeID, tickerProperty.ExchangeID.c_str(), sizeof(m_MarketData.ExchangeID));
            strncpy(m_MarketData.UpdateTime, updateTime, sizeof(m_MarketData.UpdateTime));
            strncpy(m_MarketData.RecvLocalTime, Utils::getCurrentTimeUs(), sizeof(m_MarketData.RecvLocalTime));
            m_MarketData.MillSec = 0;
            m_MarketData.LastPrice = lastPrice;
            m_MarketData.Volume = tick * 100;
            m_MarketData.Turnover = lastPrice * m_MarketData.Volume;
            m_MarketData.PreClosePrice = preClose;
            m_MarketData.OpenPrice = preClose;
            m_MarketData.HighestPrice = lastPrice + 3 * priceTick;
            m_MarketData.LowestPrice = lastPrice - 3 * priceTick;
            for(size_t level = 0; level < 10; ++level)
            {
                const double offset = static_cast<double>(level + 1) * priceTick;
                m_MarketData.BidPrice[level] = lastPrice - offset;
                m_MarketData.AskPrice[level] = lastPrice + offset;
                m_MarketData.BidVolume[level] = 1000 - static_cast<int>(level) * 50;
                m_MarketData.AskVolume[level] = 900 - static_cast<int>(level) * 50;
            }

            Message::PackMessage message;
            memset(&message, 0, sizeof(message));
            message.MessageType = Message::EMessageType::EStockMarketData;
            memcpy(&message.StockMarketData, &m_MarketData, sizeof(message.StockMarketData));
            while(!m_MarketMessageQueue.Push(message));
        }

        usleep(500*1000);
    }
}

void TestMarketGateWay::HandleCommand(const Message::TCommand& command)
{
    if(command.CmdType != Message::ECommandType::EMARKET_SUBSCRIBE)
    {
        return;
    }

    const std::string value(command.Command);
    const size_t delimiter = value.find('|');
    if(delimiter == std::string::npos)
    {
        m_Logger->Log->warn("TestMarketGateWay::HandleCommand invalid subscription:{}", value);
        return;
    }

    const std::string ticker = value.substr(0, delimiter);
    const std::string exchange = value.substr(delimiter + 1);
    if(!IsStockSubscription(ticker, exchange))
    {
        m_Logger->Log->warn("TestMarketGateWay::HandleCommand unsupported subscription:{}", value);
        return;
    }

    Utils::TickerProperty property{};
    const auto configured = m_TickerPropertyMap.find(ticker);
    if(configured != m_TickerPropertyMap.end() && configured->second.ExchangeID == exchange)
    {
        property = configured->second;
    }
    else
    {
        // 测试模式的证券主数据来自完整本地证券库，未在六只基础行情列表中的
        // 股票也按需生成确定性的模拟报价；真实模式由行情 SDK 返回可订阅标的。
        property.Index = 0;
        property.Ticker = ticker;
        property.ExchangeID = exchange;
        property.PriceTick = 0.01;
    }
    AddActiveTicker(property);
}

std::vector<Utils::TickerProperty> TestMarketGateWay::GetActiveTickers()
{
    std::lock_guard<std::mutex> lock(m_ActiveTickerMutex);
    std::vector<Utils::TickerProperty> result;
    result.reserve(m_ActiveTickerMap.size());
    for(const auto& item : m_ActiveTickerMap)
    {
        result.push_back(item.second);
    }
    return result;
}

void TestMarketGateWay::AddActiveTicker(const Utils::TickerProperty& ticker)
{
    std::lock_guard<std::mutex> lock(m_ActiveTickerMutex);
    const auto result = m_ActiveTickerMap.emplace(TickerKey(ticker), ticker);
    if(result.second)
    {
        m_Logger->Log->info("TestMarketGateWay::AddActiveTicker {}.{}", ticker.Ticker, ticker.ExchangeID);
    }
}

void TestMarketGateWay::GetCommitID(std::string& CommitID, std::string& UtilsCommitID)
{
    CommitID = SO_COMMITID;
    UtilsCommitID = SO_UTILS_COMMITID;
}

void TestMarketGateWay::GetAPIVersion(std::string& APIVersion)
{
    APIVersion = API_VERSION;
}
