#include "aster/book.hpp"
#include "aster/itch.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace aster;
namespace {
void check(bool truth, const char* condition) {
    if (!truth) throw std::runtime_error(std::string("failed: ") + condition);
}
void fails(const std::function<void()>& fn) {
    try { fn(); } catch (const std::exception&) { return; }
    throw std::runtime_error("expected failure, but operation succeeded");
}
void put(std::vector<std::byte>& buffer, std::size_t off, std::uint64_t val, int count) {
    for (int i = count - 1; i >= 0; --i) {
        buffer[off + static_cast<std::size_t>(i)] = static_cast<std::byte>(val & 255);
        val >>= 8;
    }
}
std::vector<std::byte> packet(char type, std::uint16_t locate = 4) {
    std::size_t n = 0;
    switch (type) {
        case 'A': n = 36; break;
        case 'F': n = 40; break;
        case 'E': n = 31; break;
        case 'C': n = 36; break;
        case 'X': n = 23; break;
        case 'D': n = 19; break;
        case 'U': n = 35; break;
        case 'S': n = 12; break;
        case 'P': n = 44; break;
        default: throw std::runtime_error("unsupported test fixture");
    }
    std::vector<std::byte> out(n + 2, std::byte{0});
    put(out, 0, n, 2);
    out[2] = static_cast<std::byte>(type);
    put(out, 3, locate, 2);
    put(out, 7, 12'000'000'000ULL, 6);
    return out;
}
Event parsed(const std::vector<std::byte>& v) {
    Frames f(v);
    Frame frame;
    check(f.next(frame), "fixture has a frame");
    auto event = decode(frame);
    check(!f.next(frame), "exactly one frame");
    return event;
}
Event add(std::uint64_t id, char side, std::uint32_t price, std::uint32_t qty,
          std::uint16_t locate = 4, char type = 'A') {
    auto p = packet(type, locate);
    put(p, 13, id, 8);
    p[21] = static_cast<std::byte>(side);
    put(p, 22, qty, 4);
    put(p, 34, price, 4);
    return parsed(p);
}
Event modify(char type, std::uint64_t id, std::uint32_t qty = 0,
             std::uint64_t new_id = 0, std::uint32_t price = 0,
             std::uint16_t locate = 4) {
    auto p = packet(type, locate);
    put(p, 13, id, 8);
    if (type == 'U') {
        put(p, 21, new_id, 8);
        put(p, 29, qty, 4);
        put(p, 33, price, 4);
    } else if (type == 'E' || type == 'C' || type == 'X') {
        put(p, 21, qty, 4);
        if (type == 'C') put(p, 34, price, 4);
    }
    return parsed(p);
}
void framing() {
    auto p = packet('S');
    Frames f(p);
    Frame out;
    check(f.next(out), "frame decoded");
    check(out.offset == 0 && out.payload.size() == 12, "length excludes prefix");
    check(decode(out).kind == Kind::Other, "non-book message");
    check(!f.next(out), "EOF");
    auto broken = p;
    broken.pop_back();
    fails([&] { Frames x(broken); Frame y; x.next(y); });
    for (std::size_t n = 1; n < p.size(); ++n) {
        Frames truncated(std::span(p.data(), n));
        fails([&] { Frame y; truncated.next(y); });
    }
    p[1] = std::byte{11};
    Frames length_mismatch(p);
    check(length_mismatch.next(out), "framing still valid");
    fails([&] { decode(out); });
    p[1] = std::byte{12};
    p[2] = std::byte{'z'};
    Frames unknown(p);
    check(unknown.next(out), "unknown framed");
    fails([&] { decode(out); });
}
void wire_bounds() {
    std::array<std::byte, 8> bytes{std::byte{0x12}, std::byte{0x34},
        std::byte{0x56}, std::byte{0x78}, std::byte{0x90},
        std::byte{0xab}, std::byte{0xcd}, std::byte{0xef}};
    check(wire::be(bytes, 0, 8) == 0x1234567890abcdefULL, "unaligned BE u64");
    check(wire::be(bytes, 1, 6) == 0x34567890abcdULL, "BE u48 timestamp");
    fails([&] { (void)wire::be(bytes, 7, 2); });
    fails([&] { (void)wire::be(bytes, 0, 9); });
}
void book_transitions() {
    Book book;
    book.apply(add(1, 'B', 1'000'000, 100));
    book.apply(add(2, 'B', 1'000'000, 50, 4, 'F'));
    book.apply(add(3, 'S', 1'010'000, 90));
    book.apply(add(10, 'B', 2'000'000, 8, 5));
    auto q = book.top(4);
    check(q.bid4 == 1'000'000 && q.bid_shares == 150, "same-price aggregation");
    check(q.ask4 == 1'010'000 && q.ask_shares == 90, "ask aggregation");
    check(book.queue(4, 'B', 1'000'000) == std::vector<std::uint64_t>({1, 2}),
          "add preserves FIFO position");
    auto market_buy = book.walk(4, 'B', 100);
    check(market_buy.filled == 90 && market_buy.average_price4 == 1'010'000 &&
          !market_buy.complete(), "depth walk reports partial fill without inventing depth");
    book.apply(modify('X', 1, 25));
    check(book.queue(4, 'B', 1'000'000) == std::vector<std::uint64_t>({1, 2}),
          "partial reduction preserves FIFO");
    book.apply(modify('E', 2, 50));
    q = book.top(4);
    check(q.bid_shares == 75, "cancel/execute partial and full");
    book.apply(modify('C', 3, 40, 0, 1'011'000));
    check(book.top(4).ask_shares == 50, "executed-price removes displayed shares");
    book.apply(modify('U', 1, 75, 4, 1'005'000));
    check(book.top(4).bid4 == 1'005'000, "replace moves price and id");
    check(book.queue(4, 'B', 1'005'000) == std::vector<std::uint64_t>({4}),
          "replacement gets new FIFO position");
    fails([&] { book.apply(modify('D', 1)); });
    book.apply(modify('D', 4));
    check(!book.top(4).bid4 && book.top(4).ask_shares == 50, "delete");
    fails([&] { book.apply(modify('X', 3, 51)); });
    fails([&] { book.apply(add(3, 'B', 5, 10)); });
    fails([&] { book.apply(modify('D', 3, 0, 0, 0, 5)); });
    fails([&] { book.apply(modify('U', 3, 10, 10, 3)); });
    check(book.orders() == 2, "failed updates do not change state");
    book.validate();
    check(book.walk(4, 'S', 10).filled == 0, "no bid liquidity remains");
    Book equivalent;
    equivalent.apply(add(10, 'B', 2'000'000, 8, 5));
    equivalent.apply(add(3, 'S', 1'010'000, 50));
    check(book.digest() == equivalent.digest(), "canonical digest ignores insertion order");
}
void locate_digest_checks() {
    Book first;
    first.apply(add(10, 'B', 1'000'000, 10, 4));
    first.apply(add(11, 'B', 1'000'000, 20, 4));
    first.apply(add(12, 'S', 1'010'000, 30, 5));
    auto fingerprints = first.locate_digests();
    check(fingerprints.size() == 2, "one fingerprint per nonempty locate");
    Book reordered;
    reordered.apply(add(11, 'B', 1'000'000, 20, 4));
    reordered.apply(add(10, 'B', 1'000'000, 10, 4));
    reordered.apply(add(12, 'S', 1'010'000, 30, 5));
    check(first.top(4).bid_shares == reordered.top(4).bid_shares,
          "price/quantity alone does not prove FIFO");
    check(first.locate_digests().at(4) != reordered.locate_digests().at(4),
          "changed FIFO order changes only its local fingerprint");
    check(first.locate_digests().at(5) == reordered.locate_digests().at(5),
          "other symbol fingerprint unaffected");
    first.apply(modify('D', 12, 0, 0, 0, 5));
    check(!first.locate_digests().contains(5), "empty locate omitted from fingerprints");
    first.validate();
}
void malformed_events() {
    auto p = packet('A');
    put(p, 13, 1, 8);
    p[21] = std::byte{'Z'};
    Frames f(p); Frame r;
    check(f.next(r), "frame");
    fails([&] { decode(r); });
    auto a = add(1, 'B', 100, 10);
    Book book;
    book.apply(a);
    fails([&] { book.apply(a); });
    check(book.orders() == 1 && book.top(4).bid_shares == 10, "duplicate atomicity");
}
} // namespace
int main() {
    try {
        wire_bounds();
        framing();
        book_transitions();
        locate_digest_checks();
        malformed_events();
        std::cout << "market tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
