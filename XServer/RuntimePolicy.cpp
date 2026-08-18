#include "RuntimePolicy.hpp"

#include <curl/curl.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <sstream>
#include <utility>
#include <vector>

#include "PackMessage.hpp"

namespace
{
size_t WriteResponse(char* buffer, size_t size, size_t count, void* userData)
{
    std::string* response = static_cast<std::string*>(userData);
    response->append(buffer, size * count);
    return size * count;
}

std::vector<std::string> Split(const std::string& value, char delimiter)
{
    std::vector<std::string> result;
    size_t start = 0;
    while(start <= value.size())
    {
        const size_t end = value.find(delimiter, start);
        result.push_back(value.substr(start, end == std::string::npos ? std::string::npos : end - start));
        if(end == std::string::npos)
        {
            break;
        }
        start = end + 1;
    }
    return result;
}

bool ParseBool(const std::string& value, bool& result)
{
    if(value == "0")
    {
        result = false;
        return true;
    }
    if(value == "1")
    {
        result = true;
        return true;
    }
    return false;
}

bool ParseInt(const std::string& value, int& result)
{
    if(value.empty())
    {
        return false;
    }
    char* end = nullptr;
    errno = 0;
    const long parsed = std::strtol(value.c_str(), &end, 10);
    if(errno != 0 || end != value.c_str() + value.size() ||
       parsed < std::numeric_limits<int>::min() || parsed > std::numeric_limits<int>::max())
    {
        return false;
    }
    result = static_cast<int>(parsed);
    return true;
}

bool ParseDouble(const std::string& value, double& result)
{
    if(value.empty())
    {
        return false;
    }
    char* end = nullptr;
    errno = 0;
    result = std::strtod(value.c_str(), &end);
    return errno == 0 && end == value.c_str() + value.size() && std::isfinite(result);
}

bool IsActiveStatus(const std::string& value)
{
    return value == "1";
}

bool IsDirection(const int direction, const int expected)
{
    return direction == expected;
}
}

int RuntimePolicy::Version() const
{
    return m_Version;
}

bool RuntimePolicy::Parse(const std::string& document, std::string& error)
{
    RuntimePolicy next;
    std::istringstream stream(document);
    std::string line;
    if(!std::getline(stream, line) || line != "QF_RUNTIME_POLICY\t1")
    {
        error = "runtime policy has an unsupported header";
        return false;
    }
    if(!std::getline(stream, line))
    {
        error = "runtime policy has no version";
        return false;
    }
    const std::vector<std::string> versionFields = Split(line, '\t');
    if(versionFields.size() != 2 || versionFields[0] != "VERSION" ||
       !ParseInt(versionFields[1], next.m_Version) || next.m_Version <= 0)
    {
        error = "runtime policy has an invalid version";
        return false;
    }

    std::vector<std::vector<std::string>> pendingLinks;
    size_t lineNumber = 2;
    while(std::getline(stream, line))
    {
        ++lineNumber;
        if(line.empty())
        {
            continue;
        }
        const std::vector<std::string> fields = Split(line, '\t');
        const std::string& type = fields.front();
        bool enabled = false;
        if(type == "MARKET" && fields.size() == 4)
        {
            if(fields[1].empty() || fields[2].empty() || !ParseBool(fields[3], enabled) ||
               !next.m_MarketsByExchange.emplace(fields[2], MarketRule{fields[1], enabled}).second)
            {
                error = "invalid or duplicate MARKET at line " + std::to_string(lineNumber);
                return false;
            }
        }
        else if(type == "PRODUCT" && fields.size() == 5)
        {
            int fundID = 0;
            if(!ParseInt(fields[1], fundID) || fundID <= 0 || fields[2].empty() ||
               next.m_Products.find(fundID) != next.m_Products.end())
            {
                error = "invalid or duplicate PRODUCT at line " + std::to_string(lineNumber);
                return false;
            }
            ProductRule product{fields[2], IsActiveStatus(fields[3]), {}};
            for(const std::string& market : Split(fields[4], ','))
            {
                if(!market.empty())
                {
                    product.AllowedMarkets.insert(market);
                }
            }
            next.m_Products.emplace(fundID, std::move(product));
        }
        else if(type == "PROJECT" && fields.size() == 4)
        {
            int projectID = 0;
            int fundID = 0;
            if(!ParseInt(fields[1], projectID) || projectID <= 0 || !ParseInt(fields[2], fundID) || fundID <= 0 ||
               !ParseBool(fields[3], enabled) || !next.m_Projects.emplace(projectID, ProjectRule{fundID, enabled}).second)
            {
                error = "invalid or duplicate PROJECT at line " + std::to_string(lineNumber);
                return false;
            }
        }
        else if(type == "ACCOUNT" && fields.size() == 4)
        {
            if(fields[1].empty() || fields[2].empty() || !ParseBool(fields[3], enabled) ||
               !next.m_Accounts.emplace(fields[1], AccountRule{fields[2], enabled, {}}).second)
            {
                error = "invalid or duplicate ACCOUNT at line " + std::to_string(lineNumber);
                return false;
            }
        }
        else if(type == "LINK" && fields.size() == 6)
        {
            pendingLinks.push_back(fields);
        }
        else if(type == "SECURITY" && fields.size() == 12)
        {
            bool suspended = false;
            bool buyAllowed = false;
            bool sellAllowed = false;
            bool cancelAllowed = false;
            double priceTick = 0;
            int buyUnit = 0;
            int sellUnit = 0;
            int maxQuantity = 0;
            int minQuantity = 0;
            if(fields[1].empty() || fields[2].empty() || !ParseBool(fields[3], suspended) ||
               !ParseBool(fields[4], buyAllowed) || !ParseBool(fields[5], sellAllowed) ||
               !ParseBool(fields[6], cancelAllowed) || !ParseDouble(fields[7], priceTick) || priceTick <= 0 ||
               !ParseInt(fields[8], buyUnit) || buyUnit <= 0 || !ParseInt(fields[9], sellUnit) || sellUnit <= 0 ||
               !ParseInt(fields[10], maxQuantity) || maxQuantity < 0 || !ParseInt(fields[11], minQuantity) || minQuantity < 0 ||
               (maxQuantity > 0 && minQuantity > maxQuantity) ||
               !next.m_Securities.emplace(SecurityKey(fields[1], fields[2]),
                   SecurityRule{suspended, buyAllowed, sellAllowed, cancelAllowed, priceTick, buyUnit, sellUnit,
                                maxQuantity, minQuantity, fields[1]}).second)
            {
                error = "invalid or duplicate SECURITY at line " + std::to_string(lineNumber);
                return false;
            }
        }
        else
        {
            error = "unknown or malformed runtime policy record at line " + std::to_string(lineNumber);
            return false;
        }
    }

    for(const std::vector<std::string>& fields : pendingLinks)
    {
        int projectID = 0;
        int fundID = 0;
        bool isDefault = false;
        if(!ParseInt(fields[1], projectID) || !ParseBool(fields[4], isDefault) || !ParseInt(fields[5], fundID))
        {
            error = "invalid LINK record";
            return false;
        }
        auto project = next.m_Projects.find(projectID);
        auto account = next.m_Accounts.find(fields[2]);
        auto product = next.m_Products.find(fundID);
        if(project == next.m_Projects.end() || account == next.m_Accounts.end() || product == next.m_Products.end() ||
           project->second.FundID != fundID || account->second.Type != fields[3])
        {
            error = "LINK references an inconsistent project, account, or product";
            return false;
        }
        if(isDefault && project->second.Enabled && product->second.Active)
        {
            if(product->second.AllowedMarkets.empty())
            {
                error = "LINK references a product without an allowed market";
                return false;
            }
            account->second.ProductMarkets.emplace(product->second.Code, product->second.AllowedMarkets);
        }
    }

    for(const auto& item : next.m_Securities)
    {
        const auto market = std::find_if(next.m_MarketsByExchange.begin(), next.m_MarketsByExchange.end(),
            [&item](const auto& entry) { return entry.second.MarketCode == item.second.MarketCode; });
        if(market == next.m_MarketsByExchange.end())
        {
            error = "SECURITY references a missing MARKET";
            return false;
        }
    }

    *this = std::move(next);
    error.clear();
    return true;
}

bool RuntimePolicy::CanSubscribe(const std::string& ticker, const std::string& exchange, std::string& error) const
{
    const MarketRule* market = FindMarket(exchange);
    if(!market || !market->Enabled)
    {
        error = "market is not enabled by published configuration";
        return false;
    }
    const SecurityRule* security = FindSecurity(ticker, exchange);
    if(!security || security->Suspended)
    {
        error = "security is unavailable in published configuration";
        return false;
    }
    return true;
}

bool RuntimePolicy::CanOrder(const std::string& account, const std::string& product,
                             const std::string& ticker, const std::string& exchange,
                             int direction, double price, int volume, std::string& error) const
{
    if(!CanSubscribe(ticker, exchange, error))
    {
        return false;
    }
    const auto accountRule = m_Accounts.find(account);
    if(accountRule == m_Accounts.end() || !accountRule->second.Active)
    {
        error = "account is not active in published configuration";
        return false;
    }
    const auto productMarkets = accountRule->second.ProductMarkets.find(product);
    if(productMarkets == accountRule->second.ProductMarkets.end())
    {
        error = "account is not linked to the selected active product";
        return false;
    }
    const SecurityRule* security = FindSecurity(ticker, exchange);
    if(productMarkets->second.find(security->MarketCode) == productMarkets->second.end())
    {
        error = "product is not allowed to trade this security market";
        return false;
    }
    if((IsDirection(direction, Message::EOrderDirection::EBUY) && !security->BuyAllowed) ||
       (IsDirection(direction, Message::EOrderDirection::ESELL) && !security->SellAllowed))
    {
        error = "order direction is disabled for this security";
        return false;
    }
    if(!IsDirection(direction, Message::EOrderDirection::EBUY) &&
       !IsDirection(direction, Message::EOrderDirection::ESELL))
    {
        error = "order direction is outside the published stock scope";
        return false;
    }
    const int unit = IsDirection(direction, Message::EOrderDirection::EBUY) ? security->BuyUnit : security->SellUnit;
    if(volume <= 0 || volume % unit != 0 || (security->MinQuantity > 0 && volume < security->MinQuantity) ||
       (security->MaxQuantity > 0 && volume > security->MaxQuantity))
    {
        error = "order volume violates the published security quantity rule";
        return false;
    }
    if(price <= 0 || std::fabs(std::round(price / security->PriceTick) * security->PriceTick - price) > 1e-7)
    {
        error = "order price violates the published price tick";
        return false;
    }
    return true;
}

bool RuntimePolicy::CanCancel(const std::string& account, const std::string& product,
                              const std::string& ticker, const std::string& exchange,
                              std::string& error) const
{
    const auto accountRule = m_Accounts.find(account);
    if(accountRule == m_Accounts.end() || !accountRule->second.Active || accountRule->second.ProductMarkets.empty())
    {
        error = "account is not active in published configuration";
        return false;
    }
    const MarketRule* market = FindMarket(exchange);
    if(!market || !market->Enabled)
    {
        error = "market is not enabled in published configuration";
        return false;
    }
    const auto productMarkets = accountRule->second.ProductMarkets.find(product);
    if(productMarkets == accountRule->second.ProductMarkets.end() ||
       productMarkets->second.find(market->MarketCode) == productMarkets->second.end())
    {
        error = "account is not linked to the order product and market";
        return false;
    }
    const SecurityRule* security = FindSecurity(ticker, exchange);
    if(!security)
    {
        error = "security is not present in published configuration";
        return false;
    }
    if(!security->CancelAllowed)
    {
        error = "security cancellation is disabled in published configuration";
        return false;
    }
    return true;
}

const RuntimePolicy::MarketRule* RuntimePolicy::FindMarket(const std::string& exchange) const
{
    const auto item = m_MarketsByExchange.find(exchange);
    return item == m_MarketsByExchange.end() ? nullptr : &item->second;
}

const RuntimePolicy::SecurityRule* RuntimePolicy::FindSecurity(const std::string& ticker,
                                                                const std::string& exchange) const
{
    const MarketRule* market = FindMarket(exchange);
    if(!market)
    {
        return nullptr;
    }
    const auto item = m_Securities.find(SecurityKey(market->MarketCode, ticker));
    return item == m_Securities.end() ? nullptr : &item->second;
}

std::string RuntimePolicy::SecurityKey(const std::string& marketCode, const std::string& ticker)
{
    return marketCode + ":" + ticker;
}

RuntimePolicyClient::RuntimePolicyClient(std::string serviceURL, std::string internalKey, long timeoutMs) :
    m_ServiceURL(std::move(serviceURL)),
    m_InternalKey(std::move(internalKey)),
    m_TimeoutMs(timeoutMs)
{
    while(!m_ServiceURL.empty() && m_ServiceURL.back() == '/')
    {
        m_ServiceURL.pop_back();
    }
}

bool RuntimePolicyClient::Fetch(RuntimePolicy& policy, std::string& error) const
{
    CURL* curl = curl_easy_init();
    if(!curl)
    {
        error = "unable to create runtime policy HTTP client";
        return false;
    }
    std::string response;
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Accept: text/plain");
    headers = curl_slist_append(headers, ("X-QF-Internal-Key: " + m_InternalKey).c_str());
    curl_easy_setopt(curl, CURLOPT_URL, (m_ServiceURL + "/v1/internal/config/published/runtime-policy").c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, m_TimeoutMs);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, m_TimeoutMs);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteResponse);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    const CURLcode result = curl_easy_perform(curl);
    long status = 0;
    if(result == CURLE_OK)
    {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    }
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    if(result != CURLE_OK)
    {
        error = curl_easy_strerror(result);
        return false;
    }
    if(status != 200)
    {
        error = "runtime policy service returned HTTP " + std::to_string(status);
        return false;
    }
    return policy.Parse(response, error);
}
