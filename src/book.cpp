#include "aster/book.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>

namespace aster {
namespace {
[[noreturn]] void invalid(const std::string& message) {
    throw std::runtime_error("book invariant: " + message);
}
void mix(std::uint64_t& hash, std::uint64_t v) {
    for (int i = 0; i < 8; ++i) {
        hash ^= static_cast<std::uint8_t>(v);
        hash *= 1099511628211ULL;
        v >>= 8;
    }
}
} // namespace

void Book::insert(const Order& order) {
    auto& book = books_[order.locate];
    // Callers have already verified nonzero fields, uniqueness, and overflow.
    if (order.side == 'B') {
        auto& level = book.bids[order.price4];
        level.fifo.push_back(order.id);
        auto position = std::prev(level.fifo.end());
        try {
            auto [_, ok] = orders_.emplace(order.id, Live{order, position});
            if (!ok) invalid("duplicate order id during insertion");
        } catch (...) {
            level.fifo.pop_back();
            if (level.fifo.empty()) book.bids.erase(order.price4);
            throw;
        }
        level.shares += order.shares;
    } else {
        auto& level = book.asks[order.price4];
        level.fifo.push_back(order.id);
        auto position = std::prev(level.fifo.end());
        try {
            auto [_, ok] = orders_.emplace(order.id, Live{order, position});
            if (!ok) invalid("duplicate order id during insertion");
        } catch (...) {
            level.fifo.pop_back();
            if (level.fifo.empty()) book.asks.erase(order.price4);
            throw;
        }
        level.shares += order.shares;
    }
}
void Book::remove(std::uint64_t id) {
    auto it = orders_.find(id);
    if (it == orders_.end()) invalid("remove unknown order");
    const auto order = it->second.order;
    auto& book = books_.at(order.locate);
    if (order.side == 'B') {
        auto level_it = book.bids.find(order.price4);
        if (level_it == book.bids.end() || level_it->second.shares < order.shares)
            invalid("bad bid aggregate");
        level_it->second.shares -= order.shares;
        level_it->second.fifo.erase(it->second.position);
        if (level_it->second.fifo.empty()) book.bids.erase(level_it);
    } else {
        auto level_it = book.asks.find(order.price4);
        if (level_it == book.asks.end() || level_it->second.shares < order.shares)
            invalid("bad ask aggregate");
        level_it->second.shares -= order.shares;
        level_it->second.fifo.erase(it->second.position);
        if (level_it->second.fifo.empty()) book.asks.erase(level_it);
    }
    orders_.erase(it);
}
void Book::reduce(std::uint64_t id, std::uint32_t shares) {
    auto it = orders_.find(id);
    if (it == orders_.end()) invalid("reduce unknown order");
    const auto original = it->second.order;
    if (shares == original.shares) {
        remove(id);
        return;
    }
    // Partial reductions preserve FIFO priority (no remove-and-reinsert).
    auto& book = books_.at(original.locate);
    if (original.side == 'B') book.bids.at(original.price4).shares -= shares;
    else book.asks.at(original.price4).shares -= shares;
    it->second.order.shares -= shares;
}
void Book::apply(const Event& e) {
    if (e.kind == Kind::Other) return;
    if (e.kind == Kind::Add) {
        if (!e.order || !e.shares || !e.price4 || (e.side != 'B' && e.side != 'S'))
            invalid("bad add fields");
        if (orders_.contains(e.order)) invalid("duplicate order reference");
        auto& levels = books_[e.locate];
        std::uint64_t prev = 0;
        if (e.side == 'B') {
            auto it = levels.bids.find(e.price4);
            if (it != levels.bids.end()) prev = it->second.shares;
        } else {
            auto it = levels.asks.find(e.price4);
            if (it != levels.asks.end()) prev = it->second.shares;
        }
        if (prev > std::numeric_limits<std::uint64_t>::max() - e.shares)
            invalid("aggregate overflow");
        insert(Order{e.order, e.locate, e.price4, e.shares, e.side});
        ++applied_;
        return;
    }
    const auto it = orders_.find(e.order);
    if (it == orders_.end()) invalid("unknown order reference");
    const auto original = it->second.order;
    if (e.locate != original.locate) invalid("stock locate mismatch");
    if (e.kind == Kind::Delete) {
        remove(e.order);
    } else if (e.kind == Kind::Execute || e.kind == Kind::Cancel) {
        if (!e.shares || e.shares > original.shares)
            invalid("zero or excess executed/canceled shares");
        reduce(e.order, e.shares);
    } else if (e.kind == Kind::Replace) {
        if (!e.replacement || e.replacement == e.order || !e.shares || !e.price4)
            invalid("bad replace fields");
        if (orders_.contains(e.replacement)) invalid("duplicate replacement reference");
        auto& levels = books_.at(original.locate);
        std::uint64_t prev = 0;
        if (original.side == 'B') {
            auto found = levels.bids.find(e.price4);
            if (found != levels.bids.end()) prev = found->second.shares;
        } else {
            auto found = levels.asks.find(e.price4);
            if (found != levels.asks.end()) prev = found->second.shares;
        }
        if (prev > std::numeric_limits<std::uint64_t>::max() - e.shares &&
            (e.price4 != original.price4 || e.shares > original.shares))
            invalid("replacement aggregate overflow");
        remove(e.order);
        insert(Order{e.replacement, original.locate, e.price4, e.shares, original.side});
    }
    ++applied_;
}
Quote Book::top(std::uint16_t locate) const {
    Quote q;
    auto it = books_.find(locate);
    if (it == books_.end()) return q;
    if (!it->second.bids.empty()) {
        q.bid4 = it->second.bids.begin()->first;
        q.bid_shares = it->second.bids.begin()->second.shares;
    }
    if (!it->second.asks.empty()) {
        q.ask4 = it->second.asks.begin()->first;
        q.ask_shares = it->second.asks.begin()->second.shares;
    }
    return q;
}
std::vector<std::uint64_t> Book::queue(std::uint16_t locate, char side,
                                       std::uint32_t price4) const {
    if (side != 'B' && side != 'S') invalid("invalid queue side");
    auto it = books_.find(locate);
    if (it == books_.end()) return {};
    if (side == 'B') {
        auto level = it->second.bids.find(price4);
        if (level == it->second.bids.end()) return {};
        return {level->second.fifo.begin(), level->second.fifo.end()};
    }
    auto level = it->second.asks.find(price4);
    if (level == it->second.asks.end()) return {};
    return {level->second.fifo.begin(), level->second.fifo.end()};
}
std::vector<PriceLevel> Book::levels(std::uint16_t locate, char side) const {
    if (side != 'B' && side != 'S') invalid("invalid snapshot side");
    std::vector<PriceLevel> result;
    const auto it = books_.find(locate);
    if (it == books_.end()) return result;
    const auto copy = [&](const auto& price_levels) {
        result.reserve(price_levels.size());
        for (const auto& [price, level] : price_levels) {
            PriceLevel item;
            item.price4 = price;
            item.shares = level.shares;
            item.fifo.reserve(level.fifo.size());
            for (const auto id : level.fifo) item.fifo.push_back(orders_.at(id).order);
            result.push_back(std::move(item));
        }
    };
    if (side == 'B') copy(it->second.bids);
    else copy(it->second.asks);
    return result;
}
Walk Book::walk(std::uint16_t locate, char aggressor, std::uint64_t requested) const {
    if (aggressor != 'B' && aggressor != 'S') invalid("invalid aggressor side");
    Walk out{requested, 0, 0};
    auto it = books_.find(locate);
    if (it == books_.end() || !requested) return out;
    // Sum of price(4) * quantity fits into 128 bits for uint64 requested volume.
    __extension__ typedef unsigned __int128 uint128;
    uint128 numerator = 0;
    const auto sweep = [&](const auto& levels) {
        for (auto const& [price, level] : levels) {
            auto taken = std::min(requested - out.filled, level.shares);
            numerator += static_cast<uint128>(price) * taken;
            out.filled += taken;
            if (out.filled == requested) break;
        }
    };
    if (aggressor == 'B') sweep(it->second.asks);
    else sweep(it->second.bids);
    if (out.filled) out.average_price4 = static_cast<std::uint64_t>(numerator / out.filled);
    return out;
}
std::uint64_t Book::digest() const {
    std::vector<std::uint16_t> locates;
    locates.reserve(books_.size());
    for (auto const& [locate, _] : books_) locates.push_back(locate);
    std::sort(locates.begin(), locates.end());
    std::uint64_t hash = 14695981039346656037ULL;
    for (auto locate : locates) {
        auto const& book = books_.at(locate);
        for (char side : {'B', 'S'}) {
            const auto consume = [&](const auto& levels) {
                for (auto const& [price, level] : levels) {
                    for (auto id : level.fifo) {
                        const Order& o = orders_.at(id).order;
                        mix(hash, o.locate);
                        mix(hash, static_cast<std::uint8_t>(side));
                        mix(hash, price);
                        mix(hash, id);
                        mix(hash, o.shares);
                    }
                }
            };
            if (side == 'B') consume(book.bids);
            else consume(book.asks);
        }
    }
    return hash;
}
void Book::validate() const {
    std::unordered_set<std::uint64_t> seen;
    for (auto const& [locate, book] : books_) {
        const auto validate_levels = [&](const auto& levels, char side) {
            for (auto const& [price, level] : levels) {
                if (!price || level.fifo.empty()) invalid("empty/invalid price level");
                std::uint64_t total = 0;
                for (auto it = level.fifo.begin(); it != level.fifo.end(); ++it) {
                    auto id = *it;
                    if (!seen.insert(id).second) invalid("duplicated queue entry");
                    auto order = orders_.find(id);
                    if (order == orders_.end()) invalid("queue references unknown order");
                    auto const& o = order->second.order;
                    if (o.id != id || o.locate != locate || o.price4 != price ||
                        o.side != side || !o.shares || order->second.position != it)
                        invalid("queue/order index disagreement");
                    if (total > std::numeric_limits<std::uint64_t>::max() - o.shares)
                        invalid("validation overflow");
                    total += o.shares;
                }
                if (total != level.shares) invalid("aggregate mismatch");
            }
        };
        validate_levels(book.bids, 'B');
        validate_levels(book.asks, 'S');
    }
    if (seen.size() != orders_.size()) invalid("live order absent from queues");
}
} // namespace aster
