#include "AuthzClient.hpp"

#include <curl/curl.h>

#include <algorithm>
#include <cctype>

namespace
{
size_t WriteResponse(char* buffer, size_t size, size_t count, void* userData)
{
    std::string* response = static_cast<std::string*>(userData);
    response->append(buffer, size * count);
    return size * count;
}
}

AuthzClient::AuthzClient(std::string serviceURL, std::string internalKey, long timeoutMs) :
    m_ServiceURL(std::move(serviceURL)),
    m_InternalKey(std::move(internalKey)),
    m_TimeoutMs(timeoutMs)
{
    while(!m_ServiceURL.empty() && m_ServiceURL.back() == '/')
    {
        m_ServiceURL.pop_back();
    }
}

bool AuthzClient::ValidateSession(const std::string& sessionID, AuthSessionInfo& result) const
{
    if(!IsOpaqueSessionID(sessionID))
    {
        result.Error = "invalid authorization session identifier";
        return false;
    }
    long status = 0;
    std::string body;
    if(!Request("GET", "/v1/internal/sessions/" + sessionID, "", status, body, result.Error))
    {
        return false;
    }
    if(status != 200 || !JsonBool(body, "active", result.Active))
    {
        result.Error = "authorization service rejected session";
        return false;
    }
    result.Actor = JsonString(body, "actor");
    result.UserName = JsonString(body, "username");
    result.Domain = JsonString(body, "domain");
    result.Error = JsonString(body, "reason");
    return result.Active;
}

bool AuthzClient::Authorize(const std::string& sessionID, const std::string& domain,
                            const std::string& resource, const std::string& action,
                            const std::string& traceID, std::string& error) const
{
    if(!IsOpaqueSessionID(sessionID))
    {
        error = "invalid authorization session identifier";
        return false;
    }
    const std::string body = "{\"session_id\":\"" + JsonEscape(sessionID) +
        "\",\"domain\":\"" + JsonEscape(domain) + "\",\"resource\":\"" +
        JsonEscape(resource) + "\",\"action\":\"" + JsonEscape(action) +
        "\",\"trace_id\":\"" + JsonEscape(traceID) + "\"}";
    long status = 0;
    std::string response;
    if(!Request("POST", "/v1/internal/authorize", body, status, response, error))
    {
        return false;
    }
    bool allowed = false;
    if(status != 200 || !JsonBool(response, "allowed", allowed) || !allowed)
    {
        error = JsonString(response, "reason");
        if(error.empty())
        {
            error = "authorization policy denied request";
        }
        return false;
    }
    return true;
}

bool AuthzClient::Request(const std::string& method, const std::string& path, const std::string& body,
                          long& httpStatus, std::string& response, std::string& error) const
{
    CURL* curl = curl_easy_init();
    if(!curl)
    {
        error = "unable to create HTTP client";
        return false;
    }
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, ("X-QF-Internal-Key: " + m_InternalKey).c_str());
    curl_easy_setopt(curl, CURLOPT_URL, (m_ServiceURL + path).c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, m_TimeoutMs);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, m_TimeoutMs);
    // Authorization runs on XServer's worker thread. Disable libcurl signal
    // handling so a timeout cannot interfere with another service thread.
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteResponse);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    if(method == "POST")
    {
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    }
    const CURLcode result = curl_easy_perform(curl);
    if(result == CURLE_OK)
    {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &httpStatus);
    }
    else
    {
        error = curl_easy_strerror(result);
    }
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return result == CURLE_OK;
}

bool AuthzClient::JsonBool(const std::string& json, const char* key, bool& value)
{
    const std::string prefix = std::string("\"") + key + "\":";
    const size_t start = json.find(prefix);
    if(start == std::string::npos)
    {
        return false;
    }
    const size_t valueStart = start + prefix.size();
    if(json.compare(valueStart, 4, "true") == 0)
    {
        value = true;
        return true;
    }
    if(json.compare(valueStart, 5, "false") == 0)
    {
        value = false;
        return true;
    }
    return false;
}

std::string AuthzClient::JsonString(const std::string& json, const char* key)
{
    const std::string prefix = std::string("\"") + key + "\":\"";
    const size_t start = json.find(prefix);
    if(start == std::string::npos)
    {
        return "";
    }
    std::string value;
    bool escaped = false;
    for(size_t index = start + prefix.size(); index < json.size(); ++index)
    {
        const char character = json[index];
        if(escaped)
        {
            value.push_back(character);
            escaped = false;
        }
        else if(character == '\\')
        {
            escaped = true;
        }
        else if(character == '\"')
        {
            break;
        }
        else
        {
            value.push_back(character);
        }
    }
    return value;
}

std::string AuthzClient::JsonEscape(const std::string& value)
{
    std::string escaped;
    escaped.reserve(value.size());
    for(const char character : value)
    {
        switch(character)
        {
        case '\\': escaped += "\\\\"; break;
        case '\"': escaped += "\\\""; break;
        case '\n': escaped += "\\n"; break;
        case '\r': escaped += "\\r"; break;
        case '\t': escaped += "\\t"; break;
        default:
            if(static_cast<unsigned char>(character) >= 0x20)
            {
                escaped.push_back(character);
            }
            break;
        }
    }
    return escaped;
}

bool AuthzClient::IsOpaqueSessionID(const std::string& value)
{
    return value.size() == 30 && std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isxdigit(character) != 0;
    });
}
