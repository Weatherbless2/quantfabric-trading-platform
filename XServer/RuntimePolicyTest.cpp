#include "RuntimePolicy.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

#include "PackMessage.hpp"

namespace
{
void Expect(const bool condition, const std::string& message)
{
    if(!condition)
    {
        std::cerr << "RuntimePolicyTest failure: " << message << std::endl;
        std::exit(1);
    }
}

std::string PublishedPolicy()
{
    return
        "QF_RUNTIME_POLICY\t1\n"
        "VERSION\t7\n"
        "MARKET\tS\tSSE\t1\n"
        "MARKET\tZ\tSZSE\t0\n"
        "PRODUCT\t1\tTest\t1\tS\n"
        "PROJECT\t1\t1\t1\n"
        "ACCOUNT\t188795\t0\t1\n"
        "LINK\t1\t188795\t0\t1\t1\n"
        "SECURITY\tS\t000001\t0\t1\t1\t1\t0.01\t100\t100\t10000\t100\n"
        "SECURITY\tS\t000003\t0\t1\t1\t0\t0.01\t100\t100\t10000\t100\n"
        "SECURITY\tZ\t000002\t0\t1\t1\t1\t0.01\t100\t100\t0\t100\n";
}
}

int main()
{
    RuntimePolicy policy;
    std::string error;
    Expect(policy.Parse(PublishedPolicy(), error), error);
    Expect(policy.Version() == 7, "published version must be retained");
    Expect(policy.CanSubscribe("000001", "SSE", error), error);
    Expect(!policy.CanSubscribe("000002", "SZSE", error), "disabled market must reject subscription");
    Expect(policy.CanOrder("188795", "Test", "000001", "SSE", Message::EOrderDirection::EBUY,
                           10.01, 100, error), error);
    Expect(policy.CanOrder("188795", "Test", "000001", "SSE", Message::EOrderDirection::ESELL,
                           10.01, 100, error), error);
    Expect(!policy.CanOrder("188795", "Unknown", "000001", "SSE", Message::EOrderDirection::EBUY,
                            10.01, 100, error), "unlinked product must reject order");
    Expect(!policy.CanOrder("188795", "Test", "000001", "SSE", Message::EOrderDirection::EBUY,
                            10.015, 100, error), "invalid price tick must reject order");
    Expect(!policy.CanOrder("188795", "Test", "000001", "SSE", Message::EOrderDirection::EBUY,
                            10.01, 50, error), "invalid lot size must reject order");
    Expect(policy.CanCancel("188795", "Test", "000001", "SSE", error), error);
    Expect(!policy.CanCancel("188795", "Test", "000003", "SSE", error),
           "security with cancel_allowed=false must reject cancellation");
    Expect(!policy.CanCancel("188795", "Test", "000002", "SZSE", error),
           "disabled market must reject cancellation");

    RuntimePolicy invalid;
    Expect(!invalid.Parse("QF_RUNTIME_POLICY\t1\nVERSION\t1\nLINK\t1\t188795\t0\t1\t1\n", error),
           "dangling account link must reject policy atomically");
    std::cout << "RuntimePolicyTest passed" << std::endl;
    return 0;
}
