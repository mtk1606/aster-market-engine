#include "aster/mapped_file.hpp"

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace aster {
MappedFile::MappedFile(const std::string& path) {
    fd_ = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd_ < 0) throw std::runtime_error("open " + path + ": " + std::strerror(errno));
    struct stat st{};
    if (::fstat(fd_, &st) || st.st_size < 0) {
        auto error = errno;
        ::close(fd_);
        throw std::runtime_error("fstat " + path + ": " + std::strerror(error));
    }
    if (static_cast<std::uintmax_t>(st.st_size) >
        static_cast<std::uintmax_t>(std::numeric_limits<std::size_t>::max())) {
        ::close(fd_);
        throw std::runtime_error("file too large to address");
    }
    size_ = static_cast<std::size_t>(st.st_size);
    if (size_ == 0) return;
    void* mapping = ::mmap(nullptr, size_, PROT_READ, MAP_PRIVATE, fd_, 0);
    if (mapping == MAP_FAILED) {
        auto error = errno;
        ::close(fd_);
        throw std::runtime_error("mmap " + path + ": " + std::strerror(error));
    }
    data_ = static_cast<const std::byte*>(mapping);
    (void)::madvise(const_cast<std::byte*>(data_), size_, MADV_SEQUENTIAL);
}
MappedFile::~MappedFile() {
    if (data_) ::munmap(const_cast<std::byte*>(data_), size_);
    if (fd_ >= 0) ::close(fd_);
}
} // namespace aster
