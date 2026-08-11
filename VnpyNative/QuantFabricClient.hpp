#ifndef QUANTFABRIC_CLIENT_HPP
#define QUANTFABRIC_CLIENT_HPP

#include <atomic>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

#include "HPSocket4C.h"
#include "PackMessage.hpp"

class QuantFabricClient final
{
public:
    QuantFabricClient(std::string host,
                      unsigned int port,
                      std::string user,
                      std::string password,
                      std::string sessionID,
                      std::string colo,
                      std::string product,
                      std::string account);
    ~QuantFabricClient();

    QuantFabricClient(const QuantFabricClient&) = delete;
    QuantFabricClient& operator=(const QuantFabricClient&) = delete;

    bool Start();
    bool Reconnect();
    bool Login();
    void Stop();
    bool IsConnected() const;
    bool IsLoggedIn() const;

    bool Subscribe(const std::string& ticker, const std::string& exchange);
    bool SendOrder(const std::string& ticker,
                   const std::string& exchange,
                   int direction,
                   double price,
                   int volume,
                   int orderToken);
    bool CancelOrder(const std::string& orderRef, const std::string& exchange);
    std::vector<Message::PackMessage> DrainMessages();
    std::string LastError() const;

private:
    bool Send(const Message::PackMessage& message);
    void SendLogin();
    void PushMessage(const Message::PackMessage& message);
    void SetError(const std::string& error);

    static En_HP_HandleResult __stdcall OnConnect(HP_Client sender, HP_CONNID connectionID);
    static En_HP_HandleResult __stdcall OnSend(HP_Client sender, HP_CONNID connectionID, const BYTE* data, int length);
    static En_HP_HandleResult __stdcall OnReceive(HP_Client sender, HP_CONNID connectionID, const BYTE* data, int length);
    static En_HP_HandleResult __stdcall OnClose(HP_Client sender, HP_CONNID connectionID,
                                                En_HP_SocketOperation operation, int errorCode);

    static std::atomic<QuantFabricClient*> s_instance;

    std::string m_host;
    unsigned int m_port;
    std::string m_user;
    std::string m_password;
    std::string m_sessionID;
    std::string m_colo;
    std::string m_product;
    std::string m_account;
    std::string m_uuid;
    HP_TcpPackClient m_client = nullptr;
    HP_TcpPackClientListener m_listener = nullptr;
    std::atomic_bool m_started{false};
    std::atomic_bool m_connected{false};
    std::atomic_bool m_loggedIn{false};
    std::mutex m_messageMutex;
    std::deque<Message::PackMessage> m_messages;
    mutable std::mutex m_errorMutex;
    std::string m_lastError;
};

#endif // QUANTFABRIC_CLIENT_HPP
