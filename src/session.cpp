#include "aster/session.hpp"

#include <stdexcept>
#include <string>

namespace aster {
namespace {
std::string stock_field(Frame frame, std::size_t offset) {
    std::string symbol;
    symbol.reserve(8);
    for (std::size_t i = 0; i < 8; ++i) {
        const auto c = wire::ascii(frame.payload, offset + i);
        if (c < ' ' || c > '~') throw Error(frame.offset + 2 + offset + i, "invalid stock symbol character");
        symbol += c;
    }
    const auto end = symbol.find_last_not_of(' ');
    if (end == std::string::npos) throw Error(frame.offset + 2 + offset, "empty stock symbol");
    symbol.erase(end + 1);
    if (symbol.find(' ') != std::string::npos)
        throw Error(frame.offset + 2 + offset, "embedded space in stock symbol");
    return symbol;
}
} // namespace

void SessionAudit::observe(Frame frame, const Event& event) {
    const auto type = static_cast<unsigned char>(event.raw_type);
    ++seen_;
    ++types_[type];
    // ITCH timestamps are nanoseconds since midnight, not Unix timestamps.
    if (saw_timestamp_ && event.timestamp_ns < last_timestamp_) ++regressions_;
    saw_timestamp_ = true;
    last_timestamp_ = event.timestamp_ns;

    if (closed_) throw Error(frame.offset, "message after end of messages");
    if (event.raw_type == 'S') {
        const auto code = wire::ascii(frame.payload, 11);
        if (code != 'O' && code != 'S' && code != 'Q' && code != 'M' &&
            code != 'E' && code != 'C') {
            throw Error(frame.offset + 13, "unknown system event code");
        }
        if (!opened_ && code != 'O')
            throw Error(frame.offset, "system event before start of messages");
        if (code == 'O') {
            if (opened_) throw Error(frame.offset, "duplicate start of messages");
            if (seen_ != 1)
                throw Error(frame.offset, "late start of messages");
            opened_ = true;
        } else if (code == 'C') {
            if (!opened_) throw Error(frame.offset, "end of messages before start");
            closed_ = true;
        }
        ++transitions_;
    } else if (event.raw_type == 'R') {
        if (!opened_) throw Error(frame.offset, "stock directory before start of messages");
        if (event.locate == 0) throw Error(frame.offset + 3, "stock directory uses locate zero");
        const auto stock = stock_field(frame, 11);
        // The stock-directory data occupies bytes 11..38. The leading header
        // (including tracking number and timestamp) may differ on reannouncement.
        const std::string fields(reinterpret_cast<const char*>(frame.payload.data() + 11), 28);
        const auto located = by_locate_.find(event.locate);
        const auto named = by_symbol_.find(stock);
        if (located != by_locate_.end() || named != by_symbol_.end()) {
            if (located == by_locate_.end() || located->second != stock ||
                named == by_symbol_.end() || named->second != event.locate)
                throw Error(frame.offset, "conflicting stock directory mapping");
            if (directory_fields_.at(event.locate) != fields)
                throw Error(frame.offset, "conflicting stock directory fields");
            ++directory_repeats_;
        } else {
            by_locate_.emplace(event.locate, stock);
            by_symbol_.emplace(stock, event.locate);
            directory_fields_.emplace(event.locate, fields);
            ++directories_;
        }
    } else if (event.kind == Kind::Add) {
        const auto found = by_locate_.find(event.locate);
        if (found == by_locate_.end()) throw Error(frame.offset, "order add references unknown stock locate");
        if (found->second != stock_field(frame, 24))
            throw Error(frame.offset, "order add stock differs from directory");
    } else if (event.kind != Kind::Other) {
        if (!by_locate_.contains(event.locate))
            throw Error(frame.offset, "order update references unknown stock locate");
    } else if (!opened_) {
        throw Error(frame.offset, "message before start of messages");
    }
}

void SessionAudit::require_complete() const {
    if (!opened_) throw std::runtime_error("session missing start-of-messages event");
    if (!closed_) throw std::runtime_error("session missing end-of-messages event");
    if (regressions_ != 0) throw std::runtime_error("session contains decreasing timestamps");
}

std::optional<std::uint16_t> SessionAudit::locate(std::string_view stock) const {
    const auto found = by_symbol_.find(std::string(stock));
    if (found == by_symbol_.end()) return std::nullopt;
    return found->second;
}

std::optional<std::string_view> SessionAudit::symbol(std::uint16_t stock_locate) const {
    const auto found = by_locate_.find(stock_locate);
    if (found == by_locate_.end()) return std::nullopt;
    return found->second;
}
} // namespace aster
