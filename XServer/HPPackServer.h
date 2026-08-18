#ifndef HPPACKSERVER_H
#define HPPACKSERVER_H

#include "HPSocket4C.h"
#include <string>
#include <stdio.h>
#include <string.h>
#include <cstdlib>
#include <mutex>
#include <unordered_map>
#include <unistd.h>
#include "FMTLogger.hpp"
#include "PackMessage.hpp"
#include "LockFreeQueue.hpp"
#include "phmap.h"
#include <shared_mutex>

struct Connection
{
    HP_Server pSender;
    HP_CONNID dwConnID;
    int ClientType;
    char Colo[16];
    char Account[16];
    char Actor[64];
    char SessionID[33];
    bool Authenticated;
    char AppName[32];
    char Plugins[400];
    char Messages[400];
    char UUID[32];
};

// Preserve the socket identity with the payload.  Authorization decisions must
// be bound to the authenticated connection, never to Account/Colo values that
// a client can place in a PackMessage.
struct InboundMessage
{
    HP_CONNID ConnectionID;
    Message::PackMessage Message;
};

class HPPackServer
{
public:
    HPPackServer(const char *ip, unsigned int port);
    virtual ~HPPackServer();
    void Start();
    void Stop();
    void SendData(HP_CONNID dwConnID, const unsigned char *pBuffer, int iLength);
protected:
    static En_HP_HandleResult __stdcall OnAccept(HP_Server pSender, HP_CONNID dwConnID, UINT_PTR soClient);
    static En_HP_HandleResult __stdcall OnSend(HP_Server pSender, HP_CONNID dwConnID, const BYTE *pData, int iLength);
    static En_HP_HandleResult __stdcall OnReceive(HP_Server pSender, HP_CONNID dwConnID, const BYTE *pData, int iLength);
    static En_HP_HandleResult __stdcall OnClose(HP_Server pSender, HP_CONNID dwConnID, En_HP_SocketOperation enOperation, int iErrorCode);
    static En_HP_HandleResult __stdcall OnShutdown(HP_Server pSender);
public:
    static Utils::LockFreeQueue<InboundMessage> m_PackMessageQueue;
    typedef phmap::parallel_flat_hash_map<HP_CONNID, Connection, phmap::priv::hash_default_hash<HP_CONNID>,
                                     phmap::priv::hash_default_eq<HP_CONNID>,
                                     std::allocator<std::pair<const HP_CONNID, Connection>>, 8, std::shared_mutex>
    ConnectionMapT;
    static ConnectionMapT m_sConnections;
    static ConnectionMapT m_newConnections;
private:
    std::string m_ServerIP;
    unsigned int m_ServerPort;
    HP_TcpServer m_pServer;
    HP_TcpServerListener m_pListener;
};

#endif // HPPACKSERVER_H
