#include "AuthSessionClient.h"

#include <QEventLoop>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRegularExpression>
#include <QTimer>
#include <QUrl>

AuthSessionResult AuthSessionClient::CreateDevelopmentSession(const QString& serviceURL,
                                                              const QString& username,
                                                              const QString& password)
{
    AuthSessionResult result;
    const QUrl endpoint(serviceURL + QStringLiteral("/v1/sessions/development"));
    if(!endpoint.isValid() || username.isEmpty() || password.isEmpty())
    {
        result.Error = QStringLiteral("权限服务地址、用户名和密码不能为空。");
        return result;
    }

    QNetworkAccessManager network;
    QNetworkRequest request(endpoint);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    const QJsonObject payload{{"username", username}, {"password", password}};
    QNetworkReply* reply = network.post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
    QEventLoop eventLoop;
    QTimer timeout;
    timeout.setSingleShot(true);
    QObject::connect(reply, &QNetworkReply::finished, &eventLoop, &QEventLoop::quit);
    QObject::connect(&timeout, &QTimer::timeout, &eventLoop, &QEventLoop::quit);
    timeout.start(5000);
    eventLoop.exec();

    if(!timeout.isActive())
    {
        result.Error = QStringLiteral("权限服务登录超时。");
        reply->abort();
        reply->deleteLater();
        return result;
    }
    timeout.stop();
    const QByteArray response = reply->readAll();
    const QNetworkReply::NetworkError error = reply->error();
    reply->deleteLater();
    if(error != QNetworkReply::NoError)
    {
        result.Error = QString::fromUtf8(response);
        if(result.Error.isEmpty())
        {
            result.Error = QStringLiteral("权限服务登录失败。");
        }
        return result;
    }

    result.SessionID = QJsonDocument::fromJson(response).object().value("session_id").toString();
    static const QRegularExpression sessionIDPattern(QStringLiteral("^[0-9a-f]{30}$"));
    if(!sessionIDPattern.match(result.SessionID).hasMatch())
    {
        result.SessionID.clear();
        result.Error = QStringLiteral("权限服务返回了无效会话。");
    }
    return result;
}
