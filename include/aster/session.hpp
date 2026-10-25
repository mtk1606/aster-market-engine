#pragma once

#include "aster/itch.hpp"

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>

namespace aster {

// Checks identity and lifecycle invariants which the order book alone cannot
// establish. In particular, stock locates are session-scoped, not tickers.
class SessionAudit {
public:
    void observe(Frame frame, const Event& event);
    void require_complete() const;
    std::optional<std::uint16_t> locate(std::string_view stock) const;
    std::optional<std::string_view> symbol(std::uint16_t locate) const;

    std::uint64_t directories() const { return directories_; }
    std::uint64_t directory_repeats() const { return directory_repeats_; }
    std::uint64_t transitions() const { return transitions_; }
    std::uint64_t timestamp_regressions() const { return regressions_; }
    std::uint64_t last_timestamp() const { return last_timestamp_; }
    bool opened() const { return opened_; }
    bool closed() const { return closed_; }
    const std::array<std::uint64_t, 256>& types() const { return types_; }

private:
    std::unordered_map<std::uint16_t, std::string> by_locate_;
    std::unordered_map<std::string, std::uint16_t> by_symbol_;
    // Exact 28-byte semantic payloads, excluding the message header and timestamp.
    std::unordered_map<std::uint16_t, std::string> directory_fields_;
    std::array<std::uint64_t, 256> types_{};
    std::uint64_t seen_ = 0;
    std::uint64_t directories_ = 0;
    std::uint64_t directory_repeats_ = 0;
    std::uint64_t transitions_ = 0;
    std::uint64_t regressions_ = 0;
    std::uint64_t last_timestamp_ = 0;
    bool saw_timestamp_ = false;
    bool opened_ = false;
    bool closed_ = false;
};

} // namespace aster
