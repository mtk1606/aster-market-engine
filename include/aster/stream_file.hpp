#pragma once

#include "aster/itch.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace aster {

// Length-prefixed historical-file reader using bounded buffered POSIX read().
// Frame payloads borrow storage, valid only until the next call to next().
// No frame is silently discarded at a chunk boundary or at EOF.
class ReadFrames {
public:
    explicit ReadFrames(const std::string& path, std::size_t chunk_size = 64 * 1024,
                        bool allow_terminator = false);
    ~ReadFrames();
    ReadFrames(const ReadFrames&) = delete;
    ReadFrames& operator=(const ReadFrames&) = delete;

    bool next(Frame& frame);
    std::uint64_t consumed() const { return base_ + cursor_; }
    std::size_t buffer_capacity() const { return data_.capacity(); }

private:
    bool refill();
    void compact();

    int fd_ = -1;
    std::size_t chunk_size_;
    std::vector<std::byte> data_;
    std::size_t cursor_ = 0;
    std::uint64_t base_ = 0;
    bool eof_ = false;
    bool allow_terminator_ = false;
    bool terminated_ = false;
};

} // namespace aster
