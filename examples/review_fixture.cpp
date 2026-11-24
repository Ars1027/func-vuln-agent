#include <cstddef>
#include <algorithm>

// Course review fixture: copy at most the available number of characters.
std::size_t copy_prefix(char* dest, std::size_t capacity,
                        const char* source, std::size_t available) {
    if (!dest || !source) return 0;
    const auto count = std::min(capacity, available);
    std::copy_n(source, count, dest);
    return count;
}
