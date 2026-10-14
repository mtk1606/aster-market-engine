#pragma once

#include "aster/itch.hpp"

#include <cstdint>
#include <functional>
#include <list>
#include <map>
#include <optional>
#include <unordered_map>
#include <vector>

namespace aster {
struct Order {
    std::uint64_t id;
    std::uint16_t locate;
    std::uint32_t price4;
    std::uint32_t shares;
    char side;
};
struct Quote {
    std::optional<std::uint32_t> bid4;
    std::optional<std::uint32_t> ask4;
    std::uint64_t bid_shares = 0;
    std::uint64_t ask_shares = 0;
};
struct PriceLevel {
    std::uint32_t price4 = 0;
    std::uint64_t shares = 0;
    std::vector<Order> fifo;
};
struct Walk {
    std::uint64_t requested = 0;
    std::uint64_t filled = 0;
    std::uint64_t average_price4 = 0;  // filled-share-weighted, truncated
    bool complete() const { return filled == requested; }
};

// One-writer, deterministic price-time FIFO reconstruction of displayed orders.
// Queue ordering is based on observable ITCH add/replace order; hidden liquidity,
// unobserved order entry, and strategy queue position remain outside the model.
class Book {
public:
    void apply(const Event& event);
    Quote top(std::uint16_t locate) const;
    Walk walk(std::uint16_t locate, char aggressor, std::uint64_t requested) const;
    std::vector<std::uint64_t> queue(std::uint16_t locate, char side,
                                     std::uint32_t price4) const;
    // Auditable, ordered snapshot for verification, not the hot replay path.
    std::vector<PriceLevel> levels(std::uint16_t locate, char side) const;
    std::size_t orders() const { return orders_.size(); }
    std::uint64_t applied() const { return applied_; }
    std::uint64_t digest() const; // deterministic final-state + FIFO priority hash
    // Each nonempty locate has a separate FIFO-sensitive state fingerprint.
    std::map<std::uint16_t, std::uint64_t> locate_digests() const;
    void validate() const;       // independently verify orders, queue, aggregates
private:
    struct Level {
        std::uint64_t shares = 0;
        std::list<std::uint64_t> fifo;
    };
    struct Levels {
        std::map<std::uint32_t, Level, std::greater<>> bids;
        std::map<std::uint32_t, Level> asks;
    };
    struct Live {
        Order order;
        std::list<std::uint64_t>::iterator position;
    };
    std::unordered_map<std::uint64_t, Live> orders_;
    std::unordered_map<std::uint16_t, Levels> books_;
    std::uint64_t applied_ = 0;
    void insert(const Order& order);
    void remove(std::uint64_t id);
    void reduce(std::uint64_t id, std::uint32_t shares);
};
} // namespace aster
