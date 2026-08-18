#ifndef AUTHSESSIONCLIENT_H
#define AUTHSESSIONCLIENT_H

#include <QString>

struct AuthSessionResult
{
    QString SessionID;
    QString Error;
};

class AuthSessionClient
{
public:
    // Login is outside the market and order paths, so a bounded synchronous
    // request keeps the existing Qt startup flow simple without adding a bridge.
    static AuthSessionResult CreateDevelopmentSession(const QString& serviceURL,
                                                      const QString& username,
                                                      const QString& password);
};

#endif // AUTHSESSIONCLIENT_H
