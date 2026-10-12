#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>

namespace aster {

// Market prices are integers with an implicit scale of 10,000.
struct Error : std::runtime_error {
    std::size_t offset;
    Error(std::size_t where, const std::string& message)
        : std::runtime_error(message), offset(where) {}
};

namespace wire {
inline std::uint64_t be(std::span<const std::byte> data, std::size_t offset,
                        std::size_t width) {
    if (width == 0 || width > 8 || offset > data.size() ||
        width > data.size() - offset) {
        throw Error(offset, "invalid big-endian field bounds");
    }
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < width; ++i) {
        value = (value << 8) | std::to_integer<unsigned char>(data[offset + i]);
    }
    return value;
}
inline char ascii(std::span<const std::byte> data, std::size_t offset) {
    return static_cast<char>(be(data, offset, 1));
}
}  // namespace wire

// Frames refer to borrowed storage. They must not outlive the input mapping.
struct Frame {
    std::size_t offset = 0; // byte offset of two-byte length prefix
    std::span<const std::byte> payload;
    char type() const { return wire::ascii(payload, 0); }
};

// Nasdaq downloadable historical file framing: BE u16 payload length + payload.
// This is not SoupBinTCP framing. No recovery is attempted after corruption.
class Frames {
public:
    explicit Frames(std::span<const std::byte> input, bool allow_terminator = false)
        : input_(input), allow_terminator_(allow_terminator) {}
    bool next(Frame& frame);
    std::size_t consumed() const { return cursor_; }
private:
    std::span<const std::byte> input_;
    std::size_t cursor_ = 0;
    bool allow_terminator_ = false;
};

enum class Kind : std::uint8_t { Other, Add, Execute, Cancel, Delete, Replace };
struct Event {
    Kind kind = Kind::Other;
    char raw_type = '\0';
    std::uint16_t locate = 0;
    std::uint64_t timestamp_ns = 0;
    std::uint64_t order = 0;
    std::uint64_t replacement = 0;
    std::uint32_t shares = 0;
    std::uint32_t price4 = 0;
    char side = '\0';
};

// Known ITCH 5.0 messages are size-checked even when not book-affecting.
// Unknown message types are rejected rather than silently treated as data.
Event decode(Frame frame);
std::string_view kind_name(Kind kind);

} // namespace aster
