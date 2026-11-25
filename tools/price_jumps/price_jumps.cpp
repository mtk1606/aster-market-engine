#include "price_jumps.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <string_view>

namespace aster {
namespace {
constexpr std::uint64_t ns_per_second = 1'000'000'000;
constexpr std::uint64_t start = (9 * 3600 + 35 * 60) * ns_per_second;
constexpr std::uint64_t end = (15 * 3600 + 55 * 60) * ns_per_second;
constexpr auto cooldown = 5 * ns_per_second;
constexpr std::int64_t min_mid_change_twice_price4 = 1'000;
constexpr std::int64_t min_bps = 25;

bool valid(const Quote& q) {
    return q.bid4 && q.ask4 && *q.bid4 < *q.ask4;
}

std::int64_t twice_mid(const Quote& q) {
    return static_cast<std::int64_t>(*q.bid4) + *q.ask4;
}

void write_quote(std::ostream& out, const Quote& q) {
    out << "{\"bid4\":";
    if (q.bid4) out << *q.bid4;
    else out << "null";
    out << ",\"ask4\":";
    if (q.ask4) out << *q.ask4;
    else out << "null";
    out << ",\"bid_shares\":" << q.bid_shares << ",\"ask_shares\":" << q.ask_shares
        << ",\"imbalance\":";
    if (valid(q)) {
        const auto bid = static_cast<double>(q.bid_shares);
        const auto ask = static_cast<double>(q.ask_shares);
        out << (bid - ask) / (bid + ask);
    } else {
        out << "null";
    }
    out << '}';
}

// Directory symbols are printable ASCII. Escape the two JSON delimiters.
void write_symbol(std::ostream& out, std::string_view symbol) {
    out << '"';
    for (const auto ch : symbol) {
        if (ch == '"' || ch == '\\') out << '\\';
        out << ch;
    }
    out << '"';
}
}  // namespace

void PriceJumps::observe(Book& book, Frame frame, const Event& event,
                         std::uint64_t frame_number) {
    if (event.raw_type == 'H') {
        auto& stock = stocks_[event.locate];
        const auto state = wire::ascii(frame.payload, 19);
        if (stock.trading_state != state) {
            stock.trading_state = state;
            stock.state_since = event.timestamp_ns;
            stock.history = {};
        }
        return;
    }
    if (event.kind == Kind::Other) return;

    const auto time = event.timestamp_ns;
    if (time < start - cooldown || time >= end) {
        book.apply(event);
        return;
    }

    auto& stock = stocks_[event.locate];
    const auto before = book.top(event.locate);
    const auto old = event.kind == Kind::Add
        ? Order{event.order, event.locate, event.price4, event.shares, event.side}
        : book.find_order(event.order).value();
    book.apply(event);
    const auto after = book.top(event.locate);
    const bool trading = stock.trading_state == 'T';

    if (time >= start && after.bid4 && after.ask4) {
        if (*after.bid4 > *after.ask4) {
            ++crossed_;
            stock.crossed = true;
            if (!trading) {
                ++crossed_while_nontrading_;
                stock.crossed_while_nontrading = true;
            }
            if (stock.trading_state == 'H') {
                ++crossed_while_halted_;
                stock.crossed_while_halted = true;
            }
        } else if (*after.bid4 == *after.ask4) {
            ++locked_;
        }
    }
    if (!trading) return;

    const auto side = old.side;
    const auto move = valid(before) && valid(after) ? twice_mid(after) - twice_mid(before) : 0;
    if (time >= start && time - stock.state_since >= cooldown && valid(before) && valid(after)) {
        ++eligible_;
        const auto magnitude = std::abs(move);
        if (magnitude >= min_mid_change_twice_price4 &&
            magnitude * 10'000 >= min_bps * twice_mid(before)) {
            ++count_;
            const auto bps = 10'000.0 * static_cast<double>(move) /
                             static_cast<double>(twice_mid(before));
            if (jumps_.size() < top_count || std::abs(bps) > std::abs(jumps_.back().bps)) {
                const auto position = std::find_if(jumps_.begin(), jumps_.end(), [bps](const Jump& jump) {
                    return std::abs(bps) > std::abs(jump.bps);
                });
                jumps_.insert(position, Jump{event.locate, frame_number, time, bps,
                                             event.raw_type, side, before, after, stock.history});
                if (jumps_.size() > top_count) jumps_.pop_back();
            }
        }
    }

    const auto second = time / ns_per_second;
    auto& bucket = stock.history[second % window_buckets];
    if (bucket.second != second) {
        bucket = Bucket{};
        bucket.second = second;
    }
    auto& flow = bucket.flows[side == 'B' ? 0 : 1];
    const auto record = [&](std::size_t index, std::uint32_t shares) {
        ++flow[index].messages;
        flow[index].shares += shares;
    };
    switch (event.kind) {
    case Kind::Add: record(0, event.shares); break;
    case Kind::Cancel: record(1, event.shares); break;
    case Kind::Delete: record(2, old.shares); break;
    case Kind::Execute: record(3, event.shares); break;
    case Kind::Replace:
        record(4, old.shares);
        record(5, event.shares);
        break;
    case Kind::Other: break;
    }
    bucket.closing_quote = after;
}

void PriceJumps::write_json(std::ostream& out, const SessionAudit& audit) const {
    const auto crossed_locates = std::count_if(stocks_.begin(), stocks_.end(), [](const auto& item) {
        return item.second.crossed;
    });
    const auto nontrading_locates = std::count_if(stocks_.begin(), stocks_.end(), [](const auto& item) {
        return item.second.crossed_while_nontrading;
    });
    const auto halted_locates = std::count_if(stocks_.begin(), stocks_.end(), [](const auto& item) {
        return item.second.crossed_while_halted;
    });
    out << std::setprecision(12)
        << "{\"eligible_updates\":" << eligible_ << ",\"jump_count\":" << count_
        << ",\"crossed_updates\":" << crossed_ << ",\"crossed_locates\":" << crossed_locates
        << ",\"crossed_nontrading_updates\":" << crossed_while_nontrading_
        << ",\"crossed_nontrading_locates\":" << nontrading_locates
        << ",\"crossed_halted_updates\":" << crossed_while_halted_
        << ",\"crossed_halted_locates\":" << halted_locates
        << ",\"locked_updates\":" << locked_ << ",\"top\":[";
    bool first = true;
    for (const auto& jump : jumps_) {
        if (!first) out << ',';
        first = false;
        out << "{\"symbol\":";
        write_symbol(out, audit.symbol(jump.locate).value());
        out << ",\"locate\":" << jump.locate << ",\"frame\":" << jump.frame
            << ",\"timestamp_ns\":" << jump.time << ",\"bps\":" << jump.bps
            << ",\"message\":\"" << jump.message << "\",\"side\":\"" << jump.side
            << "\",\"before\":";
        write_quote(out, jump.before);
        out << ",\"after\":";
        write_quote(out, jump.after);
        out << ",\"preceding_flow\":[";
        const auto event_second = jump.time / ns_per_second;
        for (auto second = event_second - (window_buckets - 1); second <= event_second; ++second) {
            if (second != event_second - (window_buckets - 1)) out << ',';
            const auto& saved = jump.history[second % window_buckets];
            const auto bucket = saved.second == second ? saved : Bucket{};
            out << "{\"second\":" << second << ",\"bid\":[";
            for (std::size_t side = 0; side < bucket.flows.size(); ++side) {
                if (side == 1) out << "],\"ask\":[";
                const auto& flow = bucket.flows[side];
                for (std::size_t i = 0; i < flow.size(); ++i) {
                    if (i) out << ',';
                    out << '[' << flow[i].messages << ',' << flow[i].shares << ']';
                }
            }
            out << "],\"last_quote\":";
            if (saved.second == second) write_quote(out, bucket.closing_quote);
            else out << "null";
            out << '}';
        }
        out << "]}";
    }
    out << "]}";
}
}  // namespace aster
