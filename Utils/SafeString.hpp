#ifndef SAFE_STRING_HPP
#define SAFE_STRING_HPP

#include <cstring>
#include <string>

namespace Utils
{
// PackMessage contains fixed-size C strings. Always reserve one byte for '\0'
// before those values are later read by logs, maps, or UI code.
template <size_t N>
void CopyString(char (&target)[N], const std::string& source)
{
    static_assert(N > 0, "fixed-size string cannot be empty");
    std::memset(target, 0, N);
    std::strncpy(target, source.c_str(), N - 1);
}

template <size_t N>
void CopyString(char (&target)[N], const char* source)
{
    static_assert(N > 0, "fixed-size string cannot be empty");
    std::memset(target, 0, N);
    if(source)
    {
        std::strncpy(target, source, N - 1);
    }
}

// Convert a fixed-size protocol field without assuming it was NUL-terminated.
template <size_t N>
std::string ToString(const char (&source)[N])
{
    static_assert(N > 0, "fixed-size string cannot be empty");
    return std::string(source, strnlen(source, N));
}
}

#endif // SAFE_STRING_HPP
