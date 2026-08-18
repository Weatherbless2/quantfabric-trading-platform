#include "HPPackServer.h"


HPPackServer::ConnectionMapT HPPackServer::m_sConnections;
Utils::LockFreeQueue<Message::PackMessage> HPPackServer::m_PackMessageQueue(1 << 14);

HPPackServer::HPPackServer(const char *ip, unsigned int port)
{
    m_ServerIP = ip;
    m_ServerPort = port;
    // 创建监听器对象
    m_pListener = ::Create_HP_TcpPackServerListener();
    // 创建 Socket 对象
    m_pServer = ::Create_HP_TcpPackServer(m_pListener);

    // 设置 Socket 监听器回调函数
    ::HP_Set_FN_Server_OnAccept(m_pListener, OnAccept);
    ::HP_Set_FN_Server_OnSend(m_pListener, OnSend);
    ::HP_Set_FN_Server_OnReceive(m_pListener, OnReceive);
    ::HP_Set_FN_Server_OnClose(m_pListener, OnClose);
    ::HP_Set_FN_Server_OnShutdown(m_pListener, OnShutdown);

    // 设置包头标识与最大包长限制
    ::HP_TcpPackServer_SetMaxPackSize(m_pServer, 0xFFFF);
    ::HP_TcpPackServer_SetPackHeaderFlag(m_pServer, 0x169);
    ::HP_TcpServer_SetKeepAliveTime(m_pServer, 30 * 1000);
}

HPPackServer::~HPPackServer()
{
    // 销毁 Socket 对象
    ::Destroy_HP_TcpPackServer(m_pServer);
    // 销毁监听器对象
    ::Destroy_HP_TcpPackServerListener(m_pListener);
}

void HPPackServer::Start()
{
    // EventLog
    Message::PackMessage message;
    memset(&message, 0, sizeof(message));
    message.MessageType = Message::EMessageType::EEventLog;
    char errorString[256] = {0};
    if (::HP_Server_Start(m_pServer, m_ServerIP.c_str(), m_ServerPort))
    {
        sprintf(errorString, "HPPackServer::Start listen to %s:%d successed", m_ServerIP.c_str(), m_ServerPort);
        FMTLOG(fmtlog::INF, "HPPackServer::Start listen to {}:{} successed", m_ServerIP, m_ServerPort);
        message.EventLog.Level = Message::EEventLogLevel::EINFO;
    }
    else
    {
        sprintf(errorString, "HPPackServer::Start listen to %s:%d failed, error code:%d error massage:%s",
                m_ServerIP.c_str(), m_ServerPort, ::HP_Client_GetLastError(m_pServer), HP_Client_GetLastErrorDesc(m_pServer));
        FMTLOG(fmtlog::WRN, "HPPackServer::Start listen to {}:{} failed, error code:{} error massage:{}",
                m_ServerIP, m_ServerPort, static_cast<int>(::HP_Client_GetLastError(m_pServer)),
                HP_Client_GetLastErrorDesc(m_pServer));
        message.EventLog.Level = Message::EEventLogLevel::EERROR;
    }
    strncpy(message.EventLog.App, APP_NAME, sizeof(message.EventLog.App));
    strncpy(message.EventLog.Event, errorString, sizeof(message.EventLog.Event));
    strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
    while(!m_PackMessageQueue.Push(message));
}

void HPPackServer::Stop()
{
    //停止服务器
    ::HP_Server_Stop(m_pServer);
}

void HPPackServer::SendData(HP_CONNID dwConnID, const unsigned char *pBuffer, int iLength)
{
    bool ret = ::HP_Server_Send(m_pServer, dwConnID, pBuffer, iLength);
    if(!ret)
    {
        char errorString[512] = {0};
        sprintf(errorString, "HPPackServer::SendData failed, sys error:%s, error code:%d, error message:%s",
                SYS_GetLastErrorStr(), HP_Client_GetLastError(m_pServer), HP_Client_GetLastErrorDesc(m_pServer));
        FMTLOG(fmtlog::WRN, "HPPackServer::SendData failed, sys error:{}, error code:{}, error message:{}",
                SYS_GetLastErrorStr(), static_cast<int>(HP_Client_GetLastError(m_pServer)),
                HP_Client_GetLastErrorDesc(m_pServer));

        Message::PackMessage message;
        memset(&message, 0, sizeof(message));
        message.MessageType = Message::EMessageType::EEventLog;
        message.EventLog.Level = Message::EEventLogLevel::EERROR;
        strncpy(message.EventLog.App, APP_NAME, sizeof(message.EventLog.App));
        strncpy(message.EventLog.Event, errorString, sizeof(message.EventLog.Event));
        strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
        while(!m_PackMessageQueue.Push(message));
    }
}

En_HP_HandleResult __stdcall HPPackServer::OnAccept(HP_Server pSender, HP_CONNID dwConnID, UINT_PTR soClient)
{
    TCHAR szAddress[50];
    int iAddressLen = sizeof(szAddress) / sizeof(TCHAR);
    USHORT usPort;
    ::HP_Server_GetRemoteAddress(pSender, dwConnID, szAddress, &iAddressLen, &usPort);
    Connection connection;
    memset(&connection, 0, sizeof(connection));
    connection.dwConnID = dwConnID;
    connection.pSender = pSender;
    sprintf(connection.UUID, "%d", usPort);
    auto it = m_sConnections.find(dwConnID);
    if (m_sConnections.end() == it)
    {
        m_sConnections.insert(std::pair<HP_CONNID, Connection>(dwConnID, connection));
    }
    FMTLOG(fmtlog::INF, "HPPackServer::OnAccept accept an new connection dwConnID:{} from {}:{}",  dwConnID, szAddress, usPort);
    return HR_OK;
}

En_HP_HandleResult __stdcall HPPackServer::OnSend(HP_Server pSender, HP_CONNID dwConnID, const BYTE *pData, int iLength)
{
    return HR_OK;
}

En_HP_HandleResult __stdcall HPPackServer::OnReceive(HP_Server pSender, HP_CONNID dwConnID, const BYTE *pData, int iLength)
{
    TCHAR szAddress[50];
    int iAddressLen = sizeof(szAddress) / sizeof(TCHAR);
    USHORT usPort;
    ::HP_Server_GetRemoteAddress(pSender, dwConnID, szAddress, &iAddressLen, &usPort);

    if(iLength != static_cast<int>(sizeof(Message::PackMessage)))
    {
        FMTLOG(fmtlog::WRN, "HPPackServer::OnReceive rejected invalid PackMessage size:{} expected:{}",
                iLength, sizeof(Message::PackMessage));
        return HR_OK;
    }
    Message::PackMessage message{};
    memcpy(&message, pData, sizeof(message));
    while(!m_PackMessageQueue.Push(message));
    FMTLOG(fmtlog::INF, "HPPackServer::OnReceive receive PackMessage, MessageType:{:#X} {}", message.MessageType, iLength);
    // LoginRequest
    if (Message::EMessageType::ELoginRequest == message.MessageType)
    {
        auto it = m_sConnections.find(dwConnID);
        if (it != m_sConnections.end())
        {
            it->second.ClientType = message.LoginRequest.ClientType;
            strncpy(it->second.Account, message.LoginRequest.Account, sizeof(it->second.Account));
            strncpy(it->second.PassWord, message.LoginRequest.PassWord, sizeof(it->second.PassWord));
            strncpy(it->second.UUID, message.LoginRequest.UUID, sizeof(it->second.UUID));
            char errorString[512] = {0};
            sprintf(errorString, "HPPackServer::OnReceive accept an new Client login from %s:%d, Account:%s",
                    szAddress, usPort, message.LoginRequest.Account);
            FMTLOG(fmtlog::INF, "HPPackServer::OnReceive accept an new Client login from {}:{}, Account:{}",
                    szAddress, usPort, message.LoginRequest.Account);

            Message::PackMessage msg;
            memset(&msg, 0, sizeof(msg));
            msg.MessageType = Message::EMessageType::EEventLog;
            msg.EventLog.Level = Message::EEventLogLevel::EINFO;
            strncpy(msg.EventLog.App, APP_NAME, sizeof(msg.EventLog.App));
            strncpy(msg.EventLog.Account, it->second.Account, sizeof(msg.EventLog.Account));
            strncpy(msg.EventLog.Event, errorString, sizeof(msg.EventLog.Event));
            strncpy(msg.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(msg.EventLog.UpdateTime));
            while(!m_PackMessageQueue.Push(msg));
        }
    }
    return HR_OK;
}

En_HP_HandleResult __stdcall HPPackServer::OnClose(HP_Server pSender, HP_CONNID dwConnID, En_HP_SocketOperation enOperation, int iErrorCode)
{
    TCHAR szAddress[50];
    int iAddressLen = sizeof(szAddress) / sizeof(TCHAR);
    USHORT usPort;
    ::HP_Server_GetRemoteAddress(pSender, dwConnID, szAddress, &iAddressLen, &usPort);

    auto it = m_sConnections.find(dwConnID);
    if (it != m_sConnections.end())
    {
        char errorString[512] = {0};
        sprintf(errorString, "HPPackServer::OnClose have an connection dwConnID:%llu Account:%s from %s:%d closed",
                static_cast<unsigned long long>(dwConnID), it->second.Account, szAddress, usPort);
        FMTLOG(fmtlog::WRN, "HPPackServer::OnClose have an connection dwConnID:{} Account:{} from {}:{} closed",  
                dwConnID, it->second.Account, szAddress, usPort);
        // EventLog
        Message::PackMessage message;
        memset(&message, 0, sizeof(message));
        message.MessageType = Message::EMessageType::EEventLog;
        message.EventLog.Level = Message::EEventLogLevel::EWARNING;
        strncpy(message.EventLog.App, APP_NAME, sizeof(message.EventLog.App));
        strncpy(message.EventLog.Account, it->second.Account, sizeof(message.EventLog.Account));
        strncpy(message.EventLog.Event, errorString, sizeof(message.EventLog.Event));
        strncpy(message.EventLog.UpdateTime, Utils::getCurrentTimeUs(), sizeof(message.EventLog.UpdateTime));
        while(!m_PackMessageQueue.Push(message));
        m_sConnections.erase(dwConnID);
    }
    
    return HR_OK;
}

En_HP_HandleResult __stdcall HPPackServer::OnShutdown(HP_Server pSender)
{
    return HR_OK;
}
