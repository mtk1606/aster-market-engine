#pragma once

#include "aster/book.hpp"
#include "aster/session.hpp"

#include <array>
#include <ostream>
#include <unordered_map>
#include <vector>

namespace aster {

class PriceJumps {
public:
    void observe(Book& book, Frame frame, const Event& event, std::uint64_t frame_number);
    void write_json(std::ostream& out, const SessionAudit& audit) const;

private:
    static constexpr std::size_t window_buckets = 6;
    static constexpr std::size_t top_count = 20;

    struct Flow {
        std::uint64_t messages = 0;
        std::uint64_t shares = 0;
    };
    struct Bucket {
        std::uint64_t second = 0;
        // Side (bid, ask), then add, cancel, delete, execute, replace out, replace in.
        std::array<std::array<Flow, 6>, 2> flows{};
        Quote closing_quote;
    };
    struct Stock {
        char trading_state = '\0';
        std::uint64_t state_since = 0;
        bool crossed = false;
        bool crossed_while_nontrading = false;
        bool crossed_while_halted = false;
        std::array<Bucket, window_buckets> history;
    };
    struct Jump {
        std::uint16_t locate;
        std::uint64_t frame;
        std::uint64_t time;
        double bps;
        char message;
        char side;
        Quote before;
        Quote after;
        std::array<Bucket, window_buckets> history;
    };

    std::unordered_map<std::uint16_t, Stock> stocks_;
    std::vector<Jump> jumps_;
    std::uint64_t count_ = 0;
    std::uint64_t eligible_ = 0;
    std::uint64_t crossed_ = 0;
    std::uint64_t crossed_while_nontrading_ = 0;
    std::uint64_t crossed_while_halted_ = 0;
    std::uint64_t locked_ = 0;
};
}  // namespace aster
