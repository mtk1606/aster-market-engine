#include "aster/book.hpp"
#include "aster/itch.hpp"

#include <cstddef>
#include <cstdint>
#include <exception>
#include <span>

// Fuzz the framing and decoder, including valid and malformed order streams.
// Malformed network input is expected to fail, not to terminate the process.
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* input, std::size_t count) {
    if (count > 1'000'000) return 0;
    aster::Frames reader(std::as_bytes(std::span(input, count)));
    aster::Book book;
    aster::Frame frame;
    try {
        while (reader.next(frame)) book.apply(aster::decode(frame));
    } catch (const std::exception&) {}
    book.validate();
    return 0;
}
