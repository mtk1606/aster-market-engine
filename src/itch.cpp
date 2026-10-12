#include "aster/itch.hpp"

#include <array>
#include <sstream>

namespace aster {
namespace {
std::size_t message_size(char type) {
    switch (type) {
        case 'S': return 12;
        case 'R': return 39;
        case 'H': return 25;
        case 'Y': return 20;
        case 'L': return 26;
        case 'V': return 35;
        case 'W': return 12;
        case 'K': return 28;
        case 'J': return 35;
        case 'h': return 20;
        case 'A': return 36;
        case 'F': return 40;
        case 'E': return 31;
        case 'C': return 36;
        case 'X': return 23;
        case 'D': return 19;
        case 'U': return 35;
        case 'P': return 44;
        case 'Q': return 40;
        case 'B': return 19;
        case 'I': return 50;
        case 'N': return 20;
        case 'O': return 48;
        default: return 0;
    }
}
} // namespace

bool Frames::next(Frame& frame) {
    if (cursor_ == input_.size()) return false;
    const auto start = cursor_;
    if (input_.size() - cursor_ < 2) {
        throw Error(start, "truncated frame length");
    }
    const auto length = static_cast<std::size_t>(wire::be(input_, cursor_, 2));
    if (length == 0) {
        if (!allow_terminator_) throw Error(start, "zero-length frame");
        if (input_.size() != cursor_ + 2)
            throw Error(start, "bytes after zero-length terminator");
        cursor_ += 2;
        return false;
    }
    if (length > input_.size() - cursor_ - 2) {
        throw Error(start, "truncated frame payload");
    }
    frame = Frame{start, input_.subspan(start + 2, length)};
    cursor_ += length + 2;
    return true;
}

Event decode(Frame frame) {
    const char type = frame.type();
    const auto expected = message_size(type);
    if (expected == 0) {
        throw Error(frame.offset + 2, "unknown ITCH message type");
    }
    if (frame.payload.size() != expected) {
        std::ostringstream what;
        what << "ITCH type '" << type << "' length " << frame.payload.size()
             << ", expected " << expected;
        throw Error(frame.offset, what.str());
    }
    auto get = [&](std::size_t offset, std::size_t bytes) {
        return wire::be(frame.payload, offset, bytes);
    };
    Event event;
    event.raw_type = type;
    event.locate = static_cast<std::uint16_t>(get(1, 2));
    event.timestamp_ns = get(5, 6);
    constexpr std::uint64_t day_ns = 86'400'000'000'000ULL;
    if (event.timestamp_ns >= day_ns) {
        throw Error(frame.offset + 2 + 5, "timestamp outside trading day");
    }
    switch (type) {
        case 'A':
        case 'F':
            event.kind = Kind::Add;
            event.order = get(11, 8);
            event.side = wire::ascii(frame.payload, 19);
            event.shares = static_cast<std::uint32_t>(get(20, 4));
            event.price4 = static_cast<std::uint32_t>(get(32, 4));
            if (event.side != 'B' && event.side != 'S')
                throw Error(frame.offset + 2 + 19, "invalid order side");
            break;
        case 'E':
        case 'C':
            event.kind = Kind::Execute;
            event.order = get(11, 8);
            event.shares = static_cast<std::uint32_t>(get(19, 4));
            if (type == 'C') event.price4 = static_cast<std::uint32_t>(get(32, 4));
            break;
        case 'X':
            event.kind = Kind::Cancel;
            event.order = get(11, 8);
            event.shares = static_cast<std::uint32_t>(get(19, 4));
            break;
        case 'D':
            event.kind = Kind::Delete;
            event.order = get(11, 8);
            break;
        case 'U':
            event.kind = Kind::Replace;
            event.order = get(11, 8);
            event.replacement = get(19, 8);
            event.shares = static_cast<std::uint32_t>(get(27, 4));
            event.price4 = static_cast<std::uint32_t>(get(31, 4));
            break;
        default:
            break;
    }
    return event;
}

std::string_view kind_name(Kind kind) {
    switch (kind) {
        case Kind::Other: return "other";
        case Kind::Add: return "add";
        case Kind::Execute: return "execute";
        case Kind::Cancel: return "cancel";
        case Kind::Delete: return "delete";
        case Kind::Replace: return "replace";
    }
    return "invalid";
}
} // namespace aster
