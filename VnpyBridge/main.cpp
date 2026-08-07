#include <QCoreApplication>
#include <QCommandLineParser>
#include <QDateTime>
#include <QHostAddress>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>

#include <cstring>

#include "FMTLogger.hpp"
#include "HPPackClient.h"

namespace
{
constexpr int ORDER_TYPE_LIMIT = Message::EOrderType::ELIMIT;
constexpr int BUSINESS_TYPE_STOCK = Message::EBusinessType::ESTOCK;
constexpr int ENGINE_TRADER_ORDER = Message::EEngineType::ETRADER_ORDER;
constexpr int RISK_PREPARE_CHECKED = Message::ERiskStatusType::EPREPARE_CHECKED;

template<size_t N>
void CopyText(char (&target)[N], const QString& value)
{
    const QByteArray bytes = value.toUtf8();
    std::strncpy(target, bytes.constData(), N - 1);
    target[N - 1] = '\0';
}

QByteArray JsonLine(const QJsonObject& object)
{
    return QJsonDocument(object).toJson(QJsonDocument::Compact) + '\n';
}
}

class CommandBridge final : public QObject
{
    Q_OBJECT

public:
    CommandBridge(HPPackClient& packClient,
                  const QString& colo,
                  const QString& product,
                  const QString& account,
                  bool ordersEnabled,
                  QObject *parent = nullptr) :
        QObject(parent),
        m_PackClient(packClient),
        m_Colo(colo),
        m_Product(product),
        m_Account(account),
        m_OrdersEnabled(ordersEnabled)
    {
        connect(&m_Server, &QTcpServer::newConnection, this, &CommandBridge::OnNewConnection);
        connect(&m_LoginTimer, &QTimer::timeout, this, &CommandBridge::RefreshLoginState);
        m_LoginTimer.start(500);
    }

    bool Listen(const QHostAddress& address, quint16 port)
    {
        return m_Server.listen(address, port);
    }

    QString ErrorString() const
    {
        return m_Server.errorString();
    }

    void SetLoginResponse(const Message::PackMessage& message)
    {
        SetLoggedIn(message.LoginResponse.ErrorID == 0);
    }

private slots:
    void OnNewConnection()
    {
        while(m_Server.hasPendingConnections())
        {
            QTcpSocket *socket = m_Server.nextPendingConnection();
            m_Buffers.insert(socket, QByteArray());
            connect(socket, &QTcpSocket::readyRead, this, [this, socket]() { ReadCommands(socket); });
            connect(socket, &QTcpSocket::disconnected, this, [this, socket]() {
                m_Buffers.remove(socket);
                socket->deleteLater();
            });
            SendStatus(socket);
        }
    }

private:
    void RefreshLoginState()
    {
        SetLoggedIn(HPPackClient::IsLoginSuccessed());
    }

    void SetLoggedIn(bool loggedIn)
    {
        if(m_LoggedIn == loggedIn)
        {
            return;
        }
        m_LoggedIn = loggedIn;
        m_PackClient.SetLoginSuccessed(loggedIn);
        BroadcastStatus();
    }

    void ReadCommands(QTcpSocket *socket)
    {
        QByteArray& buffer = m_Buffers[socket];
        buffer.append(socket->readAll());
        while(true)
        {
            const qsizetype newline = buffer.indexOf('\n');
            if(newline < 0)
            {
                return;
            }
            const QByteArray line = buffer.left(newline).trimmed();
            buffer.remove(0, newline + 1);
            if(!line.isEmpty())
            {
                HandleCommand(socket, line);
            }
        }
    }

    void HandleCommand(QTcpSocket *socket, const QByteArray& line)
    {
        QJsonParseError error;
        const QJsonDocument document = QJsonDocument::fromJson(line, &error);
        if(error.error != QJsonParseError::NoError || !document.isObject())
        {
            SendError(socket, "消息不是有效的 JSON 对象");
            return;
        }

        const QJsonObject command = document.object();
        const QString type = command.value("type").toString();
        if(type == "status")
        {
            SendStatus(socket);
        }
        else if(type == "order")
        {
            SendOrder(socket, command);
        }
        else if(type == "cancel")
        {
            SendCancel(socket, command);
        }
        else
        {
            SendError(socket, "不支持的命令类型");
        }
    }

    bool TradingReady(QTcpSocket *socket)
    {
        if(!m_OrdersEnabled)
        {
            SendError(socket, "交易开关未开启，请用 --enable-orders 启动 XVnpyBridge");
            return false;
        }
        if(!m_LoggedIn)
        {
            SendError(socket, "XVnpyBridge 尚未登录 XServer");
            return false;
        }
        return true;
    }

    void SendOrder(QTcpSocket *socket, const QJsonObject& command)
    {
        if(!TradingReady(socket))
        {
            return;
        }
        const QString ticker = command.value("ticker").toString().trimmed();
        const QString exchange = command.value("exchange").toString().trimmed().toUpper();
        const int direction = command.value("direction").toInt();
        const int volume = command.value("volume").toInt();
        const int orderToken = command.value("order_token").toInt();
        const double price = command.value("price").toDouble();
        if(ticker.size() != 6 || (exchange != "SSE" && exchange != "SZSE") ||
           (direction != Message::EOrderDirection::EBUY && direction != Message::EOrderDirection::ESELL) ||
           price <= 0 || volume <= 0 || volume % 100 != 0 || orderToken <= 0)
        {
            SendError(socket, "委托参数无效：仅支持沪深股票、正价格和 100 股整数倍数量");
            return;
        }

        Message::PackMessage message{};
        message.MessageType = Message::EMessageType::EOrderRequest;
        CopyText(message.OrderRequest.Colo, m_Colo);
        CopyText(message.OrderRequest.Product, m_Product);
        CopyText(message.OrderRequest.Account, m_Account);
        CopyText(message.OrderRequest.Ticker, ticker);
        CopyText(message.OrderRequest.ExchangeID, exchange);
        CopyText(message.OrderRequest.Trader, "vnpy");
        CopyText(message.OrderRequest.SendTime,
                 QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz000"));
        message.OrderRequest.BusinessType = BUSINESS_TYPE_STOCK;
        message.OrderRequest.OrderType = ORDER_TYPE_LIMIT;
        message.OrderRequest.Direction = static_cast<uint8_t>(direction);
        message.OrderRequest.Offset = Message::EOrderOffset::EOPEN;
        message.OrderRequest.RiskStatus = RISK_PREPARE_CHECKED;
        message.OrderRequest.OrderToken = orderToken;
        message.OrderRequest.EngineID = ENGINE_TRADER_ORDER;
        message.OrderRequest.Price = price;
        message.OrderRequest.Volume = volume;
        m_PackClient.SendData(reinterpret_cast<const unsigned char *>(&message), sizeof(message));

        socket->write(JsonLine({
            {"type", "command_ack"},
            {"command", "order"},
            {"accepted", true},
            {"order_token", orderToken},
        }));
    }

    void SendCancel(QTcpSocket *socket, const QJsonObject& command)
    {
        if(!TradingReady(socket))
        {
            return;
        }
        const QString orderRef = command.value("order_ref").toString().trimmed();
        const QString exchange = command.value("exchange").toString().trimmed().toUpper();
        if(orderRef.isEmpty() || (exchange != "SSE" && exchange != "SZSE"))
        {
            SendError(socket, "撤单参数无效");
            return;
        }

        Message::PackMessage message{};
        message.MessageType = Message::EMessageType::EActionRequest;
        CopyText(message.ActionRequest.Colo, m_Colo);
        CopyText(message.ActionRequest.Account, m_Account);
        CopyText(message.ActionRequest.OrderRef, orderRef);
        CopyText(message.ActionRequest.ExchangeID, exchange);
        CopyText(message.ActionRequest.Trader, "vnpy");
        CopyText(message.ActionRequest.UpdateTime,
                 QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz000"));
        message.ActionRequest.BusinessType = BUSINESS_TYPE_STOCK;
        message.ActionRequest.EngineID = ENGINE_TRADER_ORDER;
        message.ActionRequest.RiskStatus = RISK_PREPARE_CHECKED;
        m_PackClient.SendData(reinterpret_cast<const unsigned char *>(&message), sizeof(message));

        socket->write(JsonLine({
            {"type", "command_ack"},
            {"command", "cancel"},
            {"accepted", true},
            {"order_ref", orderRef},
        }));
    }

    void SendError(QTcpSocket *socket, const QString& message)
    {
        socket->write(JsonLine({
            {"type", "command_error"},
            {"error", message},
        }));
    }

    void SendStatus(QTcpSocket *socket)
    {
        socket->write(JsonLine({
            {"type", "control_status"},
            {"xserver_connected", m_LoggedIn},
            {"orders_enabled", m_OrdersEnabled},
            {"risk_check", true},
        }));
    }

    void BroadcastStatus()
    {
        for(QTcpSocket *socket : m_Buffers.keys())
        {
            SendStatus(socket);
        }
    }

    HPPackClient& m_PackClient;
    QTcpServer m_Server;
    QTimer m_LoginTimer;
    QHash<QTcpSocket *, QByteArray> m_Buffers;
    QString m_Colo;
    QString m_Product;
    QString m_Account;
    bool m_OrdersEnabled = false;
    bool m_LoggedIn = false;
};

int main(int argc, char *argv[])
{
    QCoreApplication application(argc, argv);
    QCoreApplication::setApplicationName("XVnpyBridge");

    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addOption({"xserver-host", "XServer 地址", "host", "127.0.0.1"});
    parser.addOption({"xserver-port", "XServer 端口", "port", "8000"});
    parser.addOption({"listen-host", "本机控制地址", "host", "127.0.0.1"});
    parser.addOption({"listen-port", "本机控制端口", "port", "19003"});
    parser.addOption({"user", "XServer 用户", "user", "admin"});
    parser.addOption({"password", "XServer 密码", "password", "123456"});
    parser.addOption({"colo", "交易机房", "colo", "LocalTest"});
    parser.addOption({"product", "交易产品", "product", "ATPTest"});
    parser.addOption({"account", "资金账号", "account", "610000071840"});
    parser.addOption({"enable-orders", "允许转发报单和撤单"});
    parser.process(application);

    const QString logPath = qEnvironmentVariable("APP_LOG_PATH", "./log/");
    FMTLog::Logger::Init(logPath.toStdString(), "XVnpyBridge");

    const QByteArray xserverHost = parser.value("xserver-host").toUtf8();
    const QByteArray user = parser.value("user").toUtf8();
    const QByteArray password = parser.value("password").toUtf8();
    HPPackClient packClient(xserverHost.constData(),
                            parser.value("xserver-port").toUInt(),
                            user.constData(),
                            password.constData());
    CommandBridge bridge(packClient,
                         parser.value("colo"),
                         parser.value("product"),
                         parser.value("account"),
                         parser.isSet("enable-orders"));
    QObject::connect(&packClient,
                     &HPPackClient::ReceivedLoginResponse,
                     &bridge,
                     &CommandBridge::SetLoginResponse);

    const QHostAddress listenAddress(parser.value("listen-host"));
    const quint16 listenPort = parser.value("listen-port").toUShort();
    if(!bridge.Listen(listenAddress, listenPort))
    {
        qCritical("XVnpyBridge listen failed: %s", qPrintable(bridge.ErrorString()));
        return 1;
    }

    qInfo().noquote() << JsonLine({
        {"event", "bridge_listening"},
        {"host", listenAddress.toString()},
        {"port", listenPort},
        {"orders_enabled", parser.isSet("enable-orders")},
    }).trimmed();
    packClient.Start();
    QObject::connect(&application, &QCoreApplication::aboutToQuit, [&packClient]() {
        packClient.Stop();
    });
    return application.exec();
}

#include "main.moc"
