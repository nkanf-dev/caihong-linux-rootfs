#pragma once

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

namespace caihong_compositor_comm {

constexpr unsigned char expected_build_id[] = {
    0xf5, 0xc5, 0x60, 0xdc, 0xaa, 0x16, 0xd7, 0xb2, 0x62, 0x5e,
    0xce, 0x68, 0x4b, 0x02, 0x39, 0x65, 0x05, 0xe0, 0x76, 0x8f,
};

bool basename_is(const char* value, size_t size, const char* wanted) {
    size_t begin = size;
    while (begin > 0 && value[begin - 1] != '/') --begin;
    const size_t wanted_size = std::strlen(wanted);
    return size - begin == wanted_size &&
           std::memcmp(value + begin, wanted, wanted_size) == 0;
}

bool exact_build_note(const unsigned char* data, size_t size) {
    size_t offset = 0;
    while (size - offset >= sizeof(ElfW(Nhdr))) {
        ElfW(Nhdr) note;
        std::memcpy(&note, data + offset, sizeof(note));
        offset += sizeof(note);
        const size_t padded_name = (size_t(note.n_namesz) + 3) & ~size_t(3);
        if (padded_name > size - offset) return false;
        const unsigned char* name = data + offset;
        offset += padded_name;
        if (note.n_descsz > size - offset) return false;
        if (note.n_type == NT_GNU_BUILD_ID && note.n_namesz == 4 &&
            std::memcmp(name, "GNU", 4) == 0 &&
            note.n_descsz == sizeof(expected_build_id) &&
            std::memcmp(data + offset, expected_build_id, sizeof(expected_build_id)) == 0) {
            return true;
        }
        const size_t padded_desc = (size_t(note.n_descsz) + 3) & ~size_t(3);
        if (padded_desc > size - offset) return false;
        offset += padded_desc;
    }
    return false;
}

int find_exact_main(dl_phdr_info* info, size_t, void* result) {
    const char* name = info->dlpi_name;
    if (name != nullptr && name[0] != 0 &&
        !basename_is(name, std::strlen(name), "vrcompositor.real")) return 0;
    for (unsigned i = 0; i < info->dlpi_phnum; ++i) {
        const auto& ph = info->dlpi_phdr[i];
        if (ph.p_type == PT_NOTE && exact_build_note(
                reinterpret_cast<const unsigned char*>(info->dlpi_addr + ph.p_vaddr),
                ph.p_memsz)) {
            *static_cast<bool*>(result) = true;
            return 1;
        }
    }
    return 0;
}

bool rename_main_task(pid_t pid, pid_t tid) {
    constexpr char name[] = "vrcompositor";
    if (pid == tid) return prctl(PR_SET_NAME, name, 0, 0, 0) == 0;
    // A layer may first load on RenderThread. Write the main task's comm;
    // PR_SET_NAME here would rename only RenderThread.
    char path[80];
    const int count = std::snprintf(path, sizeof(path), "/proc/self/task/%ld/comm",
                                    static_cast<long>(pid));
    if (count <= 0 || static_cast<size_t>(count) >= sizeof(path)) return false;
    const int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return false;
    ssize_t written;
    do { written = write(fd, name, sizeof(name) - 1); } while (written < 0 && errno == EINTR);
    const int saved_errno = errno;
    close(fd);
    errno = saved_errno;
    return written == static_cast<ssize_t>(sizeof(name) - 1);
}

#ifndef CAIHONG_COMM_TEST
__attribute__((constructor)) void set_compositor_main_comm() {
    bool exact_main = false;
    dl_iterate_phdr(find_exact_main, &exact_main);
    if (!exact_main) return;
    const pid_t pid = getpid();
    const pid_t tid = static_cast<pid_t>(syscall(SYS_gettid));
    if (pid <= 0 || tid <= 0) return;
    char path[80];
    const int count = std::snprintf(path, sizeof(path), "/proc/self/task/%ld/comm",
                                    static_cast<long>(pid));
    if (count <= 0 || static_cast<size_t>(count) >= sizeof(path)) return;
    const int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    char current[32] = {};
    ssize_t size;
    do { size = read(fd, current, sizeof(current) - 1); } while (size < 0 && errno == EINTR);
    close(fd);
    if (size <= 0 || size >= static_cast<ssize_t>(sizeof(current) - 1)) return;
    if (current[size - 1] == '\n') current[--size] = 0;
    if (std::strcmp(current, "vrcompositor.re") != 0 &&
        std::strcmp(current, "vrcompositor") != 0) return;
    const bool changed = rename_main_task(pid, tid);
    std::fprintf(stderr, "ALVR_COMPOSITOR_COMM status=%s pid=%ld tid=%ld name=vrcompositor\n",
                 changed ? "set" : "failed", static_cast<long>(pid), static_cast<long>(tid));
}
#endif

} // namespace caihong_compositor_comm
