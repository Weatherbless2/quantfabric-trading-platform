#ifndef ORDER_TRACE_HPP
#define ORDER_TRACE_HPP

#include <cstring>
#include <string>

namespace Utils
{
template <size_t AccountSize, size_t RefSize>
std::string OrderTraceID(const char (&account)[AccountSize], int orderToken,
                         const char (&orderRef)[RefSize])
{
    const std::string accountText(account, strnlen(account, AccountSize));
    if(orderToken > 0)
    {
        return "QF-" + accountText + "-" + std::to_string(orderToken);
    }
    const std::string refText(orderRef, strnlen(orderRef, RefSize));
    return "QF-" + accountText + "-REF-" + (refText.empty() ? "UNKNOWN" : refText);
}

template <size_t AccountSize>
std::string OrderTraceID(const char (&account)[AccountSize], int orderToken)
{
    const char emptyRef[1] = {0};
    return OrderTraceID(account, orderToken, emptyRef);
}
}

#endif // ORDER_TRACE_HPP
