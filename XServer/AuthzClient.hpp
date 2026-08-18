#ifndef AUTHZCLIENT_HPP
#define AUTHZCLIENT_HPP

#include <string>

struct AuthSessionInfo
{
    bool Active = false;
    std::string Actor;
    std::string UserName;
    std::string Domain;
    std::string Error;
};

class AuthzClient
{
public:
    AuthzClient(std::string serviceURL, std::string internalKey, long timeoutMs);

    bool ValidateSession(const std::string& sessionID, AuthSessionInfo& result) const;
    bool Authorize(const std::string& sessionID, const std::string& domain,
                   const std::string& resource, const std::string& action,
                   const std::string& traceID, std::string& error) const;

private:
    bool Request(const std::string& method, const std::string& path, const std::string& body,
                 long& httpStatus, std::string& response, std::string& error) const;
    static bool JsonBool(const std::string& json, const char* key, bool& value);
    static std::string JsonString(const std::string& json, const char* key);
    static std::string JsonEscape(const std::string& value);
    static bool IsOpaqueSessionID(const std::string& value);

    std::string m_ServiceURL;
    std::string m_InternalKey;
    long m_TimeoutMs;
};

#endif // AUTHZCLIENT_HPP
