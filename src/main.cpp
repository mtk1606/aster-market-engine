#include "aster/book.hpp"
#include "aster/itch.hpp"
#include "aster/session.hpp"
#include "aster/mapped_file.hpp"
#include "aster/stream_file.hpp"

#include <chrono>
#include <charconv>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
std::uint64_t number(std::string_view raw) {
    std::uint64_t out = 0;
    const auto [ptr, ec] = std::from_chars(raw.data(), raw.data() + raw.size(), out);
    if (ec != std::errc{} || ptr != raw.data() + raw.size())
        throw std::runtime_error("invalid numeric option");
    return out;
}
void json_string(std::string_view value) {
    std::cout << '"';
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned char ch : value) {
        if (ch == '"' || ch == '\\') std::cout << '\\' << static_cast<char>(ch);
        else if (ch < 0x20) std::cout << "\\u00" << digits[ch >> 4] << digits[ch & 15];
        else std::cout << static_cast<char>(ch);
    }
    std::cout << '"';
}
void display(std::optional<std::uint32_t> price) {
    if (!price) std::cout << "null";
    else std::cout << *price;
}
void snapshot(const std::vector<aster::PriceLevel>& levels) {
    std::cout << '[';
    bool first = true;
    for (const auto& level : levels) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "{\"price4\":" << level.price4
                  << ",\"shares\":" << level.shares << ",\"orders\":[";
        bool first_order = true;
        for (const auto& order : level.fifo) {
            if (!first_order) std::cout << ',';
            first_order = false;
            std::cout << '[' << order.id << ',' << order.shares << ']';
        }
        std::cout << "]}";
    }
    std::cout << ']';
}
} // namespace
int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: aster-replay FILE [--io mmap|read] [--chunk N] "
                     "[--locate N|--symbol STOCK] [--limit N] [--validate] "
                     "[--audit] [--complete] [--snapshot] [--walk B|S N] [--locate-digests]\n";
        return 2;
    }
    try {
        std::optional<std::uint16_t> locate;
        std::optional<std::string> selected_symbol;
        bool audit_enabled = false;
        bool require_complete = false;
        std::uint64_t limit = UINT64_MAX;
        std::uint64_t checkpoint_interval = 0;
        struct Checkpoint {
            std::uint64_t frame;
            std::uint64_t applied;
            std::size_t live_orders;
            std::uint64_t digest;
        };
        std::vector<Checkpoint> checkpoints;
        bool validate = false;
        bool show_snapshot = false;
        bool show_locate_digests = false;
        char walk_side = '\0';
        std::uint64_t walk_size = 0;
        std::string_view io = "mmap";
        std::size_t chunk_size = 65536;
        bool custom_chunk = false;
        for (int i = 2; i < argc; ++i) {
            const std::string_view arg(argv[i]);
            if ((arg == "--locate" || arg == "--limit" || arg == "--chunk" || arg == "--checkpoint-interval") && i + 1 < argc) {
                const auto value = number(argv[++i]);
                if (arg == "--locate") {
                    if (value > UINT16_MAX) throw std::runtime_error("locate out of range");
                    locate = static_cast<std::uint16_t>(value);
                } else if (arg == "--limit") limit = value;
                else if (arg == "--checkpoint-interval") {
                    if (value == 0) throw std::runtime_error("checkpoint interval must be positive");
                    checkpoint_interval = value;
                } else {
                    if (value < 1 || value > 8 * 1024 * 1024)
                        throw std::runtime_error("chunk size must be 1..8388608");
                    chunk_size = static_cast<std::size_t>(value);
                    custom_chunk = true;
                }
            } else if (arg == "--io" && i + 1 < argc) {
                io = argv[++i];
                if (io != "mmap" && io != "read")
                    throw std::runtime_error("--io must be mmap or read");
            } else if (arg == "--symbol" && i + 1 < argc) {
                selected_symbol = argv[++i];
                if (selected_symbol->empty()) throw std::runtime_error("empty symbol");
                audit_enabled = true;
            } else if (arg == "--walk" && i + 2 < argc) {
                const std::string_view side = argv[++i];
                if (side != "B" && side != "S")
                    throw std::runtime_error("--walk side must be B or S");
                walk_side = side.front();
                walk_size = number(argv[++i]);
            } else if (arg == "--validate") validate = true;
            else if (arg == "--audit") audit_enabled = true;
            else if (arg == "--complete") { audit_enabled = true; require_complete = true; }
            else if (arg == "--snapshot") show_snapshot = true;
            else if (arg == "--locate-digests") show_locate_digests = true;
            else throw std::runtime_error("unknown option: " + std::string(arg));
        }
        if (selected_symbol && locate) throw std::runtime_error("choose --locate or --symbol, not both");
        if (require_complete && limit != UINT64_MAX)
            throw std::runtime_error("--complete cannot be used with --limit");
        if (walk_side && !locate && !selected_symbol)
            throw std::runtime_error("--walk requires --locate or --symbol");
        if (show_snapshot && !locate && !selected_symbol)
            throw std::runtime_error("--snapshot requires --locate or --symbol");
        if (custom_chunk && io != "read") throw std::runtime_error("--chunk requires --io read");

        // The mapping or read buffer must outlive each borrowed Frame.
        std::unique_ptr<aster::MappedFile> mapping;
        std::unique_ptr<aster::Frames> mapped;
        std::unique_ptr<aster::ReadFrames> streamed;
        if (io == "mmap") {
            mapping = std::make_unique<aster::MappedFile>(argv[1]);
            mapped = std::make_unique<aster::Frames>(mapping->bytes(), require_complete);
        } else {
            streamed = std::make_unique<aster::ReadFrames>(argv[1], chunk_size, require_complete);
        }
        aster::Book book;
        aster::SessionAudit audit;
        aster::Frame frame;
        std::uint64_t frames = 0, ignored = 0;
        const auto start = std::chrono::steady_clock::now();
        try {
            while (frames < limit && (streamed ? streamed->next(frame) : mapped->next(frame))) {
                const auto event = aster::decode(frame);
                if (audit_enabled) audit.observe(frame, event);
                if (event.kind == aster::Kind::Other) ++ignored;
                else book.apply(event);
                ++frames;
                if (checkpoint_interval && frames % checkpoint_interval == 0) {
                    checkpoints.push_back({frames, book.applied(), book.orders(), book.digest()});
                }
            }
        } catch (const aster::Error& e) {
            throw std::runtime_error("byte " + std::to_string(e.offset) + ": " + e.what());
        } catch (const std::exception& e) {
            throw std::runtime_error("frame at byte " + std::to_string(frame.offset) +
                                     ": " + e.what());
        }
        const auto end = std::chrono::steady_clock::now();
        if (checkpoint_interval && (checkpoints.empty() || checkpoints.back().frame != frames)) {
            checkpoints.push_back({frames, book.applied(), book.orders(), book.digest()});
        }
        if (validate) book.validate();
        if (require_complete) audit.require_complete();
        if (selected_symbol) {
            locate = audit.locate(*selected_symbol);
            if (!locate) throw std::runtime_error("symbol not found in stock directory: " + *selected_symbol);
        }
        const auto elapsed = std::chrono::duration<double>(end - start).count();
        std::cout << "{\"io\":\"" << io << "\",\"frames\":" << frames
                  << ",\"bytes_consumed\":" << (streamed ? streamed->consumed() : mapped->consumed())
                  << ",\"applied\":" << book.applied()
                  << ",\"ignored\":" << ignored << ",\"live_orders\":" << book.orders()
                  << ",\"digest\":\"" << std::hex << book.digest() << std::dec
                  << "\",\"elapsed_seconds\":" << std::fixed << std::setprecision(6)
                  << elapsed << ",\"frames_per_second\":"
                  << (elapsed > 0 ? static_cast<double>(frames) / elapsed : 0);
        if (checkpoint_interval) {
            std::cout << ",\"checkpoints\":[";
            bool first = true;
            for (const auto& checkpoint : checkpoints) {
                if (!first) std::cout << ',';
                first = false;
                std::cout << "{\"frame\":" << checkpoint.frame
                          << ",\"applied\":" << checkpoint.applied
                          << ",\"live_orders\":" << checkpoint.live_orders
                          << ",\"digest\":\"" << std::hex << checkpoint.digest
                          << std::dec << "\"}";
            }
            std::cout << ']';
        }
        if (show_locate_digests) {
            std::cout << ",\"locate_digests\":{";
            bool first = true;
            for (const auto& [book_locate, hash] : book.locate_digests()) {
                if (!first) std::cout << ',';
                first = false;
                std::cout << '"' << book_locate << "\":\""
                          << std::hex << hash << std::dec << '"';
            }
            std::cout << '}';
        }
        if (audit_enabled) {
            std::cout << ",\"audit\":{\"directories\":" << audit.directories()
                      << ",\"system_events\":" << audit.transitions()
                      << ",\"opened\":" << (audit.opened() ? "true" : "false")
                      << ",\"closed\":" << (audit.closed() ? "true" : "false")
                      << ",\"timestamp_regressions\":" << audit.timestamp_regressions()
                      << ",\"last_timestamp_ns\":" << audit.last_timestamp()
                      << ",\"types\":{";
            bool first_type = true;
            for (std::size_t index = 0; index < audit.types().size(); ++index) {
                const auto count = audit.types()[index];
                if (!count) continue;
                if (!first_type) std::cout << ',';
                first_type = false;
                const char name = static_cast<char>(index);
                json_string(std::string_view(&name, 1));
                std::cout << ':' << count;
            }
            std::cout << "}}";
        }
        if (locate) {
            const auto q = book.top(*locate);
            std::cout << ",\"locate\":" << *locate;
            if (audit_enabled) {
                if (const auto stock = audit.symbol(*locate)) {
                    std::cout << ",\"symbol\":";
                    json_string(*stock);
                }
            }
            std::cout << ",\"bid4\":";
            display(q.bid4);
            std::cout << ",\"bid_shares\":" << q.bid_shares << ",\"ask4\":";
            display(q.ask4);
            std::cout << ",\"ask_shares\":" << q.ask_shares;
            if (walk_side) {
                const auto walk = book.walk(*locate, walk_side, walk_size);
                std::cout << ",\"walk_requested\":" << walk.requested
                          << ",\"walk_filled\":" << walk.filled
                          << ",\"walk_avg4\":" << walk.average_price4
                          << ",\"walk_complete\":"
                          << (walk.complete() ? "true" : "false");
            }
            if (show_snapshot) {
                std::cout << ",\"snapshot\":{\"bids\":";
                snapshot(book.levels(*locate, 'B'));
                std::cout << ",\"asks\":";
                snapshot(book.levels(*locate, 'S'));
                std::cout << '}';
            }
        }
        std::cout << "}\n";
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << '\n';
        return 1;
    }
}
