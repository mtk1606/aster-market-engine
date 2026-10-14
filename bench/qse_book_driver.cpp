// Optional comparison driver. Requires an authorized local QSE checkout at build time.
// No QSE implementation is redistributed by this file.
#include "qse/data/OrderBookFullDepth.h"
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Operation {
    char kind = 0;
    std::uint64_t id = 0;
    char side = 0;
    std::uint32_t price4 = 0;
    std::uint32_t shares = 0;
};
struct Live {
    qse::QueueId qid = 0;
    qse::Order::Side side = qse::Order::Side::BUY;
    qse::Price price = 0;
};
void require(bool check, const char* why) {
    if (!check) throw std::runtime_error(why);
}
std::vector<Operation> read_workload(const char* filename) {
    std::ifstream input(filename);
    require(bool(input), "cannot open workload");
    std::vector<Operation> operations;
    std::string line, suffix;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream fields(line);
        Operation op;
        std::uint64_t price = 0, shares = 0;
        require(bool(fields >> op.kind >> op.id) && op.id != 0, "bad operation");
        if (op.kind == 'A') {
            require(bool(fields >> op.side >> price >> shares), "bad add");
            require((op.side == 'B' || op.side == 'S') && price != 0 && shares != 0 &&
                    price <= std::numeric_limits<std::uint32_t>::max() &&
                    shares <= std::numeric_limits<std::uint32_t>::max(), "invalid add value");
            op.price4 = static_cast<std::uint32_t>(price);
            op.shares = static_cast<std::uint32_t>(shares);
        } else {
            require(op.kind == 'D', "unknown operation");
        }
        require(!(fields >> suffix), "trailing fields");
        operations.push_back(op);
    }
    require(!operations.empty(), "empty workload");
    return operations;
}
void mix(std::uint64_t& state, std::uint64_t value) {
    for (int i = 0; i < 8; ++i) {
        state ^= static_cast<std::uint8_t>(value);
        state *= 1099511628211ULL;
        value >>= 8;
    }
}
void print_optional(bool exists, std::uint32_t value) {
    if (exists) std::cout << value; else std::cout << "null";
}
std::uint32_t unscale(double price) {
    const double value = price * 10000.0;
    require(value > 0.0 && value <= double(std::numeric_limits<std::uint32_t>::max()), "invalid book price");
    return static_cast<std::uint32_t>(std::llround(value));
}
}

int main(int argc, char** argv) {
    try {
        require(argc == 2, "usage: qse-book-bench WORKLOAD.tsv");
        const auto operations = read_workload(argv[1]);
        qse::OrderBookFullDepth book;
        std::vector<Live> live(operations.size() + 2);
        std::size_t live_count = 0;
        const auto started = std::chrono::steady_clock::now();
        for (const auto& op : operations) {
            require(op.id < live.size(), "ID outside expected range");
            auto& entry = live[static_cast<std::size_t>(op.id)];
            if (op.kind == 'A') {
                require(entry.qid == 0, "duplicate ID");
                const auto side = op.side == 'B' ? qse::Order::Side::BUY : qse::Order::Side::SELL;
                const auto price = static_cast<double>(op.price4) / 10000.0;
                const auto qid = book.enqueue_order(side, price, std::to_string(op.id), op.shares);
                require(qid != 0, "QSE rejected add");
                entry = {qid, side, price};
                ++live_count;
            } else {
                require(entry.qid != 0, "missing ID");
                require(book.cancel_order(entry.qid), "QSE rejected delete");
                book.remove_level_if_empty(entry.side, entry.price);
                entry.qid = 0;
                --live_count;
            }
        }
        const auto stopped = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration<double>(stopped - started).count();
        const auto top = book.top_of_book();
        std::uint64_t hash = 14695981039346656037ULL;
        std::size_t observed_live = 0;
        for (char marker : {'B','S'}) {
            const auto side = marker == 'B' ? qse::Order::Side::BUY : qse::Order::Side::SELL;
            auto prices = book.top_n_prices(side, operations.size());
            mix(hash, static_cast<unsigned char>(marker));
            mix(hash, prices.size());
            for (const auto price : prices) {
                auto consumed = book.consume_at_price(side, price, std::numeric_limits<qse::Volume>::max());
                std::uint64_t shares = 0;
                for (const auto& [id, volume] : consumed) shares += volume;
                mix(hash, unscale(price));
                mix(hash, shares);
                mix(hash, consumed.size());
                for (const auto& [id, volume] : consumed) {
                    const std::uint64_t numeric_id = std::stoull(id);
                    require(numeric_id < live.size() && live[numeric_id].qid != 0, "orphan in QSE book");
                    mix(hash, numeric_id);
                    mix(hash, volume);
                    ++observed_live;
                }
            }
        }
        require(observed_live == live_count, "remaining book size mismatch");
        std::ostringstream repr;
        repr << std::hex << std::setfill('0') << std::setw(16) << hash;
        std::cout << "{\"schema\":\"order-book-comparison-v1\",\"engine\":\"qse\",\"operations\":"
                  << operations.size() << ",\"live_orders\":" << live_count
                  << ",\"elapsed_seconds\":" << std::setprecision(15) << elapsed
                  << ",\"state_hash\":\"" << repr.str() << "\",\"bid4\":";
        print_optional(top.best_bid_size != 0, top.best_bid_size != 0 ? unscale(top.best_bid_price) : 0);
        std::cout << ",\"ask4\":";
        print_optional(top.best_ask_size != 0, top.best_ask_size != 0 ? unscale(top.best_ask_price) : 0);
        std::cout << ",\"bid_shares\":" << top.best_bid_size
                  << ",\"ask_shares\":" << top.best_ask_size << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "QSE benchmark failed: " << error.what() << '\n';
        return 1;
    }
}
