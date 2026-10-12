#include "aster/book.hpp"

#include <cstddef>
#include <cstdint>
#include <exception>
#include <span>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* input, std::size_t count) {
    // Convert arbitrary bytes into a sequence of both valid and adversarial
    // book transitions. Every rejected mutation must leave the book unchanged.
    if (count > 300'000) return 0;
    aster::Book book;
    const auto bytes = std::as_bytes(std::span(input, count));
    for (std::size_t pos = 0; pos + 19 <= bytes.size(); pos += 19) {
        const auto field = [&](std::size_t off, std::size_t width) {
            return aster::wire::be(bytes, pos + off, width);
        };
        aster::Event event;
        const auto action = field(0, 1) % 5;
        event.kind = action == 0 ? aster::Kind::Add :
                     action == 1 ? aster::Kind::Execute :
                     action == 2 ? aster::Kind::Cancel :
                     action == 3 ? aster::Kind::Delete : aster::Kind::Replace;
        event.locate = static_cast<std::uint16_t>(field(1, 1) % 4);
        event.order = field(2, 2) % 300;
        event.replacement = field(4, 2) % 300;
        event.price4 = static_cast<std::uint32_t>(field(6, 4) % 10000);
        event.shares = static_cast<std::uint32_t>(field(10, 4) % 10000);
        event.side = field(14, 1) % 2 ? 'B' : 'S';
        const auto before = book.digest();
        const auto before_count = book.orders();
        try {
            book.apply(event);
        } catch (const std::exception&) {
            if (book.digest() != before || book.orders() != before_count)
                __builtin_trap();
        }
    }
    book.validate();
    return 0;
}
