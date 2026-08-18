#include "PyTdxMarketGateWay.h"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <sstream>
#include <yaml-cpp/yaml.h>
#include "XPluginEngine.hpp"

CreateObjectFunc(PyTdxMarketGateWay);

namespace
{
template <typename T>
T ValueOr(const YAML::Node& node, const char *key, const T& fallback)
{
    return node[key] ? node[key].as<T>() : fallback;
}
}

PyTdxMarketGateWay::PyTdxMarketGateWay() :
    MarketGateWay(),
    m_BridgeHost("127.0.0.1"),
    m_BridgePort(19001),
    m_Socket(-1),
    m_Tick(0)
{
}

PyTdxMarketGateWay::~PyTdxMarketGateWay()
{
    if(m_Socket >= 0)
    {
        close(m_Socket);
    }
}

bool PyTdxMarketGateWay::LoadAPIConfig()
{
    try
    {
        YAML::Node config = YAML::LoadFile(m_MarketCenterConfig.APIConfig);
        YAML::Node bridge = config["PyTdxBridgeConfig"];
        if(!bridge)
        {
            m_Logger->Log->error("PyTdxMarketGateWay::LoadAPIConfig missing PyTdxBridgeConfig in {}",
                                 m_MarketCenterConfig.APIConfig);
            return false;
        }
        m_BridgeHost = ValueOr<std::string>(bridge, "Host", "127.0.0.1");
        m_BridgePort = ValueOr<int>(bridge, "Port", 19001);
        m_Logger->Log->info("PyTdxMarketGateWay::LoadAPIConfig Bridge:{}:{}",
                            m_BridgeHost, m_BridgePort);
        return true;
    }
    catch(const std::exception& error)
    {
        m_Logger->Log->error("PyTdxMarketGateWay::LoadAPIConfig failed: {}", error.what());
        return false;
    }
}

int PyTdxMarketGateWay::ConnectBridge()
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

bool PyTdxMarketGateWay::ParseQuote(const std::string& line, Message::PackMessage& message)
{
    try
    {
        // JSON 是 YAML 的严格子集，复用项目现有 yaml-cpp，避免引入第二套解析库。
        YAML::Node quote = YAML::Load(line);
        if(ValueOr<std::string>(quote, "type", "") != "stock_quote")
        {
            return false;
        }

        memset(&message, 0, sizeof(message));
        message.MessageType = Message::EMessageType::EStockMarketData;
        MarketData::TStockMarketData& data = message.StockMarketData;
        data.Tick = m_Tick++;
        strncpy(data.Ticker, ValueOr<std::string>(quote, "ticker", "").c_str(), sizeof(data.Ticker));
        strncpy(data.ExchangeID, ValueOr<std::string>(quote, "exchange", "").c_str(), sizeof(data.ExchangeID));
        strncpy(data.UpdateTime, ValueOr<std::string>(quote, "update_time", "").c_str(), sizeof(data.UpdateTime));
        strncpy(data.RecvLocalTime, Utils::getCurrentTimeUs(), sizeof(data.RecvLocalTime));
        data.MillSec = ValueOr<int>(quote, "millisec", 0);
        data.LastPrice = ValueOr<double>(quote, "last_price", 0);
        data.Volume = ValueOr<int>(quote, "volume", 0);
        data.Turnover = ValueOr<double>(quote, "turnover", 0);
        data.PreClosePrice = ValueOr<double>(quote, "pre_close", 0);
        data.OpenPrice = ValueOr<double>(quote, "open", 0);
        data.HighestPrice = ValueOr<double>(quote, "high", 0);
        data.LowestPrice = ValueOr<double>(quote, "low", 0);

        const YAML::Node bidPrices = quote["bid_prices"];
        const YAML::Node bidVolumes = quote["bid_volumes"];
        const YAML::Node askPrices = quote["ask_prices"];
        const YAML::Node askVolumes = quote["ask_volumes"];
        for(size_t i = 0; i < 10; ++i)
        {
            data.BidPrice[i] = bidPrices && i < bidPrices.size() ? bidPrices[i].as<double>() : 0;
            data.BidVolume[i] = bidVolumes && i < bidVolumes.size() ? bidVolumes[i].as<int>() : 0;
            data.AskPrice[i] = askPrices && i < askPrices.size() ? askPrices[i].as<double>() : 0;
            data.AskVolume[i] = askVolumes && i < askVolumes.size() ? askVolumes[i].as<int>() : 0;
        }
        return data.Ticker[0] != '\0';
    }
    catch(const std::exception& error)
    {
        m_Logger->Log->warn("PyTdxMarketGateWay::ParseQuote invalid payload: {}", error.what());
        return false;
    }
}

void PyTdxMarketGateWay::HandleCommand(const Message::TCommand& command)
{
    if(command.CmdType != Message::ECommandType::EMARKET_SUBSCRIBE)
    {
        return;
    }
    std::string value(command.Command);
    const size_t delimiter = value.find('|');
    if(delimiter == std::string::npos)
    {
        m_Logger->Log->warn("PyTdxMarketGateWay::HandleCommand invalid subscription:{}", value);
        return;
    }
    const std::string ticker = value.substr(0, delimiter);
    const std::string exchange = value.substr(delimiter + 1);
    if(ticker.size() != 6 || (exchange != "SSE" && exchange != "SZSE"))
    {
        m_Logger->Log->warn("PyTdxMarketGateWay::HandleCommand unsupported subscription:{}", value);
        return;
    }

    std::ostringstream payload;
    payload << "{\"type\":\"subscribe\",\"ticker\":\"" << ticker
            << "\",\"exchange\":\"" << exchange << "\"}\n";
    const std::string text = payload.str();
    std::lock_guard<std::mutex> lock(m_SocketMutex);
    if(m_Socket < 0)
    {
        m_Logger->Log->warn("PyTdxMarketGateWay::HandleCommand bridge is disconnected");
        return;
    }
    size_t sent = 0;
    while(sent < text.size())
    {
        const ssize_t length = send(m_Socket, text.data() + sent, text.size() - sent, MSG_NOSIGNAL);
        if(length <= 0)
        {
            m_Logger->Log->warn("PyTdxMarketGateWay::HandleCommand send failed, errno:{}", errno);
            return;
        }
        sent += static_cast<size_t>(length);
    }
    m_Logger->Log->info("PyTdxMarketGateWay::HandleCommand subscribed {}", value);
}

void PyTdxMarketGateWay::Run()
{
    std::string pending;
    char buffer[4096];
    while(true)
    {
        {
            std::lock_guard<std::mutex> lock(m_SocketMutex);
            m_Socket = ConnectBridge();
        }
        if(m_Socket < 0)
        {
            m_Logger->Log->warn("PyTdxMarketGateWay::Run bridge {}:{} unavailable",
                                m_BridgeHost, m_BridgePort);
            sleep(1);
            continue;
        }
        m_Logger->Log->info("PyTdxMarketGateWay::Run connected to bridge {}:{}",
                            m_BridgeHost, m_BridgePort);

        pending.clear();
        ssize_t received = 0;
        while((received = recv(m_Socket, buffer, sizeof(buffer), 0)) > 0)
        {
            pending.append(buffer, static_cast<size_t>(received));
            size_t newline = std::string::npos;
            while((newline = pending.find('\n')) != std::string::npos)
            {
                Message::PackMessage message;
                if(ParseQuote(pending.substr(0, newline), message))
                {
                    while(!m_MarketMessageQueue.Push(message));
                }
                pending.erase(0, newline + 1);
            }
        }

        {
            std::lock_guard<std::mutex> lock(m_SocketMutex);
            close(m_Socket);
            m_Socket = -1;
        }
        m_Logger->Log->warn("PyTdxMarketGateWay::Run bridge disconnected, errno:{}", errno);
        sleep(1);
    }
}

void PyTdxMarketGateWay::GetCommitID(std::string& CommitID, std::string& UtilsCommitID)
{
    CommitID = SO_COMMITID;
    UtilsCommitID = SO_UTILS_COMMITID;
}

void PyTdxMarketGateWay::GetAPIVersion(std::string& APIVersion)
{
    APIVersion = API_VERSION;
}
