#ifndef RUNTIMEPOLICY_HPP
#define RUNTIMEPOLICY_HPP

#include <string>
#include <unordered_map>
#include <unordered_set>

// The policy is intentionally small: it is the published configuration that
// XServer needs for admission checks, not a mirror of the control-plane DB.
// Instances are immutable after Parse(), so one can be safely swapped between
// the configuration reload thread and the PackMessage worker.
class RuntimePolicy final
{
public:
    int Version() const;
    bool Parse(const std::string& document, std::string& error);

    bool CanSubscribe(const std::string& ticker, const std::string& exchange,
                      std::string& error) const;
    bool CanOrder(const std::string& account, const std::string& product,
                  const std::string& ticker, const std::string& exchange,
                  int direction, double price, int volume, std::string& error) const;
    bool CanCancel(const std::string& account, const std::string& product,
                   const std::string& ticker, const std::string& exchange,
                   std::string& error) const;

private:
    struct MarketRule
    {
        std::string MarketCode;
        bool Enabled = false;
    };

    struct ProductRule
    {
        std::string Code;
        bool Active = false;
        std::unordered_set<std::string> AllowedMarkets;
    };

    struct ProjectRule
    {
        int FundID = 0;
        bool Enabled = false;
    };

    struct AccountRule
    {
        std::string Type;
        bool Active = false;
        // Product code -> published market codes. One account may be linked
        // to several products, each with a different market scope.
        std::unordered_map<std::string, std::unordered_set<std::string>> ProductMarkets;
    };

    struct SecurityRule
    {
        bool Suspended = false;
        bool BuyAllowed = false;
        bool SellAllowed = false;
        bool CancelAllowed = false;
        double PriceTick = 0;
        int BuyUnit = 0;
        int SellUnit = 0;
        int MaxQuantity = 0;
        int MinQuantity = 0;
        std::string MarketCode;
    };

    const MarketRule* FindMarket(const std::string& exchange) const;
    const SecurityRule* FindSecurity(const std::string& ticker, const std::string& exchange) const;
    static std::string SecurityKey(const std::string& marketCode, const std::string& ticker);

    int m_Version = 0;
    std::unordered_map<std::string, MarketRule> m_MarketsByExchange;
    std::unordered_map<int, ProductRule> m_Products;
    std::unordered_map<int, ProjectRule> m_Projects;
    std::unordered_map<std::string, AccountRule> m_Accounts;
    std::unordered_map<std::string, SecurityRule> m_Securities;
};

class RuntimePolicyClient final
{
public:
    RuntimePolicyClient(std::string serviceURL, std::string internalKey, long timeoutMs);

    bool Fetch(RuntimePolicy& policy, std::string& error) const;

private:
    std::string m_ServiceURL;
    std::string m_InternalKey;
    long m_TimeoutMs;
};

#endif // RUNTIMEPOLICY_HPP
