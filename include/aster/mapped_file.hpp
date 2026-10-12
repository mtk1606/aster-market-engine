#pragma once
#include <cstddef>
#include <span>
#include <string>

namespace aster {
class MappedFile {
public:
    explicit MappedFile(const std::string& path);
    ~MappedFile();
    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;
    std::span<const std::byte> bytes() const { return {data_, size_}; }
private:
    int fd_ = -1;
    const std::byte* data_ = nullptr;
    std::size_t size_ = 0;
};
} // namespace aster
