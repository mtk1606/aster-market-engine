#include "aster/stream_file.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/types.h>
#include <unistd.h>

namespace aster {
ReadFrames::ReadFrames(const std::string& path, std::size_t chunk_size, bool allow_terminator)
    : chunk_size_(chunk_size), allow_terminator_(allow_terminator) {
    // Each historical ITCH payload is a u16-framed record, so a 1-byte
    // chunk is legal and useful for exercising carry-over logic in tests.
    if (chunk_size_ == 0 || chunk_size_ > 8 * 1024 * 1024)
        throw std::invalid_argument("read chunk size must be 1..8388608 bytes");
    data_.reserve(chunk_size_ + 65537);
    fd_ = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd_ < 0) throw std::runtime_error("open " + path + ": " + std::strerror(errno));
}
ReadFrames::~ReadFrames() {
    if (fd_ >= 0) ::close(fd_);
}
void ReadFrames::compact() {
    if (cursor_ == 0) return;
    base_ += cursor_;
    const auto tail = data_.size() - cursor_;
    if (tail) std::memmove(data_.data(), data_.data() + cursor_, tail);
    data_.resize(tail);
    cursor_ = 0;
}
bool ReadFrames::refill() {
    if (eof_) return false;
    compact();
    const auto prev = data_.size();
    data_.resize(prev + chunk_size_);
    ssize_t count;
    do {
        count = ::read(fd_, data_.data() + prev, chunk_size_);
    } while (count < 0 && errno == EINTR);
    if (count < 0) {
        const int code = errno;
        data_.resize(prev);
        throw std::runtime_error(std::string("read: ") + std::strerror(code));
    }
    data_.resize(prev + static_cast<std::size_t>(count));
    if (count == 0) eof_ = true;
    return count != 0;
}
bool ReadFrames::next(Frame& frame) {
    if (terminated_) return false;
    while (data_.size() - cursor_ < 2 && refill()) {}
    const auto remaining = data_.size() - cursor_;
    if (remaining == 0) return false;
    const auto where = base_ + cursor_;
    if (remaining < 2) throw Error(static_cast<std::size_t>(where), "truncated frame length");
    const auto length = static_cast<std::size_t>(wire::be(
        std::span<const std::byte>(data_.data(), data_.size()), cursor_, 2));
    if (length == 0) {
        if (!allow_terminator_) throw Error(static_cast<std::size_t>(where), "zero-length frame");
        if (remaining > 2 || refill())
            throw Error(static_cast<std::size_t>(where), "bytes after zero-length terminator");
        // refill() can compact the buffer, invalidating the previous cursor.
        cursor_ += 2;
        terminated_ = true;
        return false;
    }
    while (data_.size() - cursor_ - 2 < length && refill()) {}
    if (data_.size() - cursor_ - 2 < length)
        throw Error(static_cast<std::size_t>(where), "truncated frame payload");
    frame = Frame{static_cast<std::size_t>(where),
                  std::span<const std::byte>(data_.data() + cursor_ + 2, length)};
    cursor_ += length + 2;
    return true;
}
} // namespace aster
