#ifndef PYTDXMARKETGATEWAY_H
#define PYTDXMARKETGATEWAY_H

#include <mutex>
#include <string>
#include "MarketGateWay.hpp"

class PyTdxMarketGateWay : public MarketGateWay
{
public:
    explicit PyTdxMarketGateWay();
    virtual ~PyTdxMarketGateWay();

    virtual bool LoadAPIConfig();
    virtual void Run();
    virtual void HandleCommand(const Message::TCommand& command);
    virtual void GetCommitID(std::string& CommitID, std::string& UtilsCommitID);
    virtual void GetAPIVersion(std::string& APIVersion);

private:
    int ConnectBridge();
    bool ParseQuote(const std::string& line, Message::PackMessage& message);

    std::string m_BridgeHost;
    int m_BridgePort;
    int m_Socket;
    int m_Tick;
    std::mutex m_SocketMutex;
};

#endif // PYTDXMARKETGATEWAY_H
