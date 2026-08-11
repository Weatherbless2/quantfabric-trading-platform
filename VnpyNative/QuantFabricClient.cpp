#include "QuantFabricClient.hpp"

#include <algorithm>
#include <cstring>
#include <utility>

#include "SafeString.hpp"

namespace
{
constexpr size_t MAX_PENDING_MESSAGES = 65536;

template <size_t N>
std::string Text(const char (&value)[N])
{
    const size_t length = std::find(value, value + N, '\0') - value;
    return std::string(value, length);
}

bool IsStockExchange(const std::string& exchange)
{
    return exchange == "SSE" || exchange == "SZSE";
}
}

std::atomic<QuantFabricClient*> QuantFabricClient::s_instance{nullptr};

QuantFabricClient::QuantFabricClient(std::string host,
                                     unsigned int port,
                                     std::string user,
                                     std::string password,
                                     std::string sessionID,
                                     std::string colo,
                                     std::string product,
                                     std::string account) :
    m_host(std::move(host)),
    m_port(port),
    m_user(std::move(user)),
    m_password(std::move(password)),
    m_sessionID(std::move(sessionID)),
    m_colo(std::move(colo)),
    m_product(std::move(product)),
    m_account(std::move(account))
{
    m_listener = ::Create_HP_TcpPackClientListener();
    m_client = ::Create_HP_TcpPackClient(m_listener);
    ::HP_Set_FN_Client_OnConnect(m_listener, OnConnect);
    ::HP_Set_FN_Client_OnSend(m_listener, OnSend);
    ::HP_Set_FN_Client_OnReceive(m_listener, OnReceive);
    ::HP_Set_FN_Client_OnClose(m_listener, OnClose);
    ::HP_TcpPackClient_SetMaxPackSize(m_client, 0xFFFF);
    ::HP_TcpPackClient_SetPackHeaderFlag(m_client, 0x169);
    ::HP_TcpClient_SetKeepAliveTime(m_client, 30 * 1000);
}

QuantFabricClient::~QuantFabricClient()
{
    Stop();
    if(m_client)
    {
        ::Destroy_HP_TcpPackClient(m_client);
    }
    if(m_listener)
    {
        ::Destroy_HP_TcpPackClientListener(m_listener);
    }
}

bool QuantFabricClient::Start()
{
    if(m_started.exchange(true))
    {
        return true;
    }

    if(!m_sessionID.empty() && m_sessionID.size() != 30)
    {
        SetError("authorization session ID must contain 30 characters");
        m_started.store(false);
        return false;
    }

    QuantFabricClient* expected = nullptr;
    if(!s_instance.compare_exchange_strong(expected, this))
    {
        SetError("only one QuantFabricClient can use the HP-Socket callbacks");
        m_started.store(false);
        return false;
    }

    if(!::HP_Client_Start(m_client, m_host.c_str(), m_port, false))
    {
        SetError(::HP_Client_GetLastErrorDesc(m_client));
        s_instance.store(nullptr);
        m_started.store(false);
        return false;
    }
    // HP-Socket completes the TCP handshake before HP_Client_Start returns.
    // Send from this stable point instead of sending the login packet twice
    // (once here and once in the connection callback).
    SendLogin();
    return true;
}

bool QuantFabricClient::Reconnect()
{
    if(IsConnected())
    {
        return true;
    }
    Stop();
    return Start();
}

bool QuantFabricClient::Login()
{
    if(!IsConnected())
    {
        SetError("XServer connection is not ready");
        return false;
    }
    SendLogin();
    return true;
}

void QuantFabricClient::Stop()
{
    if(!m_started.exchange(false))
    {
        return;
    }
    ::HP_Client_Stop(m_client);
    m_connected.store(false);
    m_loggedIn.store(false);
    QuantFabricClient* expected = this;
    s_instance.compare_exchange_strong(expected, nullptr);
}

bool QuantFabricClient::IsConnected() const
{
    return m_connected.load();
}

bool QuantFabricClient::IsLoggedIn() const
{
    return m_loggedIn.load();
}

bool QuantFabricClient::Subscribe(const std::string& ticker, const std::string& exchange)
{
    if(!IsLoggedIn())
    {
        SetError("XServer is not logged in");
        return false;
    }
    if(ticker.size() != 6 || !IsStockExchange(exchange))
    {
        SetError("invalid stock subscription");
        return false;
    }

    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::ECommand;
    message.Command.CmdType = Message::ECommandType::EMARKET_SUBSCRIBE;
    Utils::CopyString(message.Command.Colo, m_colo);
    Utils::CopyString(message.Command.Account, m_account);
    Utils::CopyString(message.Command.Command, ticker + "|" + exchange);
    return Send(message);
}

bool QuantFabricClient::SendOrder(const std::string& ticker,
                                  const std::string& exchange,
                                  int direction,
                                  double price,
                                  int volume,
                                  int orderToken)
{
    if(!IsLoggedIn())
    {
        SetError("XServer is not logged in");
        return false;
    }
    if(ticker.size() != 6 || !IsStockExchange(exchange) ||
       (direction != Message::EOrderDirection::EBUY && direction != Message::EOrderDirection::ESELL) ||
       price <= 0 || volume <= 0 || volume % 100 != 0 || orderToken <= 0)
    {
        SetError("invalid stock limit order");
        return false;
    }

    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::EOrderRequest;
    Utils::CopyString(message.OrderRequest.Colo, m_colo);
    Utils::CopyString(message.OrderRequest.Product, m_product);
    Utils::CopyString(message.OrderRequest.Account, m_account);
    Utils::CopyString(message.OrderRequest.Ticker, ticker);
    Utils::CopyString(message.OrderRequest.ExchangeID, exchange);
    Utils::CopyString(message.OrderRequest.Trader, "vnpy");
    message.OrderRequest.BusinessType = Message::EBusinessType::ESTOCK;
    message.OrderRequest.OrderType = Message::EOrderType::ELIMIT;
    message.OrderRequest.Direction = static_cast<uint8_t>(direction);
    message.OrderRequest.Offset = Message::EOrderOffset::EOPEN;
    message.OrderRequest.RiskStatus = Message::ERiskStatusType::EPREPARE_CHECKED;
    message.OrderRequest.OrderToken = orderToken;
    message.OrderRequest.EngineID = Message::EEngineType::ETRADER_ORDER;
    message.OrderRequest.Price = price;
    message.OrderRequest.Volume = volume;
    return Send(message);
}

bool QuantFabricClient::CancelOrder(const std::string& orderRef, const std::string& exchange)
{
    if(!IsLoggedIn())
    {
        SetError("XServer is not logged in");
        return false;
    }
    if(orderRef.empty() || !IsStockExchange(exchange))
    {
        SetError("invalid cancel request");
        return false;
    }

    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::EActionRequest;
    Utils::CopyString(message.ActionRequest.Colo, m_colo);
    Utils::CopyString(message.ActionRequest.Account, m_account);
    Utils::CopyString(message.ActionRequest.OrderRef, orderRef);
    Utils::CopyString(message.ActionRequest.ExchangeID, exchange);
    Utils::CopyString(message.ActionRequest.Trader, "vnpy");
    message.ActionRequest.BusinessType = Message::EBusinessType::ESTOCK;
    message.ActionRequest.EngineID = Message::EEngineType::ETRADER_ORDER;
    message.ActionRequest.RiskStatus = Message::ERiskStatusType::EPREPARE_CHECKED;
    return Send(message);
}

std::vector<Message::PackMessage> QuantFabricClient::DrainMessages()
{
    std::lock_guard<std::mutex> lock(m_messageMutex);
    std::vector<Message::PackMessage> messages;
    messages.reserve(m_messages.size());
    while(!m_messages.empty())
    {
        messages.push_back(m_messages.front());
        m_messages.pop_front();
    }
    return messages;
}

std::string QuantFabricClient::LastError() const
{
    std::lock_guard<std::mutex> lock(m_errorMutex);
    return m_lastError;
}

bool QuantFabricClient::Send(const Message::PackMessage& message)
{
    if(!m_connected.load())
    {
        SetError("XServer connection is closed");
        return false;
    }
    if(!::HP_Client_Send(m_client, reinterpret_cast<const unsigned char*>(&message), sizeof(message)))
    {
        SetError(::HP_Client_GetLastErrorDesc(m_client));
        return false;
    }
    return true;
}

void QuantFabricClient::SendLogin()
{
    Message::PackMessage message{};
    message.MessageType = Message::EMessageType::ELoginRequest;
    message.LoginRequest.ClientType = Message::EClientType::EXMONITOR;
    Utils::CopyString(message.LoginRequest.Account, m_user);
    Utils::CopyString(message.LoginRequest.Colo, m_colo);
    if(m_sessionID.empty())
    {
        // Legacy XServer installations still use the local credential table.
        Utils::CopyString(message.LoginRequest.PassWord, m_password);
        Utils::CopyString(message.LoginRequest.UUID, m_uuid);
    }
    else
    {
        // The opaque session is validated by AuthAdminService. Do not place the
        // desktop password in a packet once session authentication is active.
        Utils::CopyString(message.LoginRequest.UUID, m_sessionID);
    }
    Send(message);
}

void QuantFabricClient::PushMessage(const Message::PackMessage& message)
{
    std::lock_guard<std::mutex> lock(m_messageMutex);
    if(m_messages.size() == MAX_PENDING_MESSAGES)
    {
        m_messages.pop_front();
        SetError("message queue reached its limit; oldest message was dropped");
    }
    m_messages.push_back(message);
}

void QuantFabricClient::SetError(const std::string& error)
{
    std::lock_guard<std::mutex> lock(m_errorMutex);
    m_lastError = error;
}

En_HP_HandleResult __stdcall QuantFabricClient::OnConnect(HP_Client sender, HP_CONNID connectionID)
{
    QuantFabricClient* client = s_instance.load();
    if(client)
    {
        TCHAR address[50] = {0};
        int addressLength = sizeof(address) / sizeof(TCHAR);
        USHORT port = 0;
        if(::HP_Client_GetLocalAddress(sender, address, &addressLength, &port))
        {
            client->m_uuid = std::to_string(port);
        }
        client->m_connected.store(true);
    }
    return HR_OK;
}

En_HP_HandleResult __stdcall QuantFabricClient::OnSend(HP_Client sender, HP_CONNID connectionID, const BYTE* data, int length)
{
    return HR_OK;
}

En_HP_HandleResult __stdcall QuantFabricClient::OnReceive(HP_Client sender, HP_CONNID connectionID, const BYTE* data, int length)
{
    QuantFabricClient* client = s_instance.load();
    if(!client || length != static_cast<int>(sizeof(Message::PackMessage)))
    {
        return HR_OK;
    }
    Message::PackMessage message{};
    std::memcpy(&message, data, sizeof(message));
    if(message.MessageType == Message::EMessageType::ELoginResponse)
    {
        // An admin receives permission rows for other users after its own
        // successful response. A successful reply is sufficient to mark the
        // session ready; only this user's explicit failure clears that state.
        if(message.LoginResponse.ErrorID == 0)
        {
            client->m_loggedIn.store(true);
        }
        else if(Text(message.LoginResponse.Account) == client->m_user)
        {
            client->m_loggedIn.store(false);
            client->SetError("XServer login rejected");
        }
    }
    client->PushMessage(message);
    return HR_OK;
}

En_HP_HandleResult __stdcall QuantFabricClient::OnClose(HP_Client sender, HP_CONNID connectionID,
                                                         En_HP_SocketOperation operation, int errorCode)
{
    QuantFabricClient* client = s_instance.load();
    if(client)
    {
        client->m_connected.store(false);
        client->m_loggedIn.store(false);
        client->SetError(::HP_Client_GetLastErrorDesc(sender));
    }
    return HR_OK;
}
