#include "aster/book.hpp"

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace {
struct Operation {
    char kind;
    std::uint64_t id;
    char side = '\0';
    std::uint32_t price4 = 0;
    std::uint32_t shares = 0;
};

std::vector<Operation> load(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open workload");
    std::vector<Operation> operations;
    std::string line;
    std::size_t lineno = 0;
    while (std::getline(input, line)) {
        ++lineno;
        if (line.empty() || line[0] == '#') continue;
        std::istringstream s(line);
        Operation op{};
        std::string tail;
        // No signed values belong in this workload protocol.
        if (line.find_first_of("+-") != std::string::npos)
            throw std::runtime_error("signed field at line " + std::to_string(lineno));
        if (!(s >> op.kind >> op.id) || op.id == 0) throw std::runtime_error("bad operation at line " + std::to_string(lineno));
        if (op.kind == 'A') {
            std::uint64_t p = 0, q = 0;
            if (!(s >> op.side >> p >> q) || (op.side != 'B' && op.side != 'S') ||
                p == 0 || p > std::numeric_limits<std::uint32_t>::max() ||
                q == 0 || q > std::numeric_limits<std::uint32_t>::max())
                throw std::runtime_error("bad add at line " + std::to_string(lineno));
            op.price4 = static_cast<std::uint32_t>(p);
            op.shares = static_cast<std::uint32_t>(q);
        } else if (op.kind != 'D') {
            throw std::runtime_error("unsupported operation at line " + std::to_string(lineno));
        }
        if (s >> tail) throw std::runtime_error("trailing data at line " + std::to_string(lineno));
        operations.push_back(op);
    }
    if (operations.empty()) throw std::runtime_error("empty workload");
    return operations;
}
void mix(std::uint64_t& state, std::uint64_t val) {
    for (int i = 0; i < 8; ++i) {
        state ^= static_cast<unsigned char>(val);
        state *= 1099511628211ULL;
        val >>= 8;
    }
}
std::uint64_t state_hash(const aster::Book& book) {
    std::uint64_t state = 14695981039346656037ULL;
    for (char side : {'B', 'S'}) {
        auto levels = book.levels(7, side);
        mix(state, static_cast<unsigned char>(side));
        mix(state, levels.size());
        for (const auto& level : levels) {
            mix(state, level.price4);
            mix(state, level.shares);
            mix(state, level.fifo.size());
            for (const auto& order : level.fifo) {
                mix(state, order.id);
                mix(state, order.shares);
            }
        }
    }
    return state;
}
void optional_price(const std::optional<std::uint32_t>& price) {
    if (price) std::cout << *price;
    else std::cout << "null";
}
}

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("usage: aster-book-bench WORKLOAD.tsv");
        const auto operations = load(argv[1]);
        aster::Book book;
        const auto start = std::chrono::steady_clock::now();
        for (const auto& op : operations) {
            aster::Event e{};
            e.locate = 7;
            e.order = op.id;
            if (op.kind == 'A') {
                e.kind = aster::Kind::Add;
                e.side = op.side;
                e.price4 = op.price4;
                e.shares = op.shares;
            } else {
                e.kind = aster::Kind::Delete;
            }
            book.apply(e);
        }
        const auto end = std::chrono::steady_clock::now();
        book.validate();
        const auto elapsed = std::chrono::duration<double>(end - start).count();
        const auto quote = book.top(7);
        const auto hash = state_hash(book);
        std::ostringstream encoded;
        encoded << std::hex << std::setfill('0') << std::setw(16) << hash;
        std::cout << "{\"schema\":\"order-book-comparison-v1\",\"engine\":\"aster\",\"operations\":"
                  << operations.size() << ",\"live_orders\":" << book.orders()
                  << ",\"elapsed_seconds\":" << std::setprecision(14) << elapsed
                  << ",\"state_hash\":\"" << encoded.str() << "\",\"bid4\":";
        optional_price(quote.bid4);
        std::cout << ",\"ask4\":";
        optional_price(quote.ask4);
        std::cout << ",\"bid_shares\":" << quote.bid_shares
                  << ",\"ask_shares\":" << quote.ask_shares << "}\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "book benchmark failed: " << ex.what() << '\n';
        return 1;
    }
}
