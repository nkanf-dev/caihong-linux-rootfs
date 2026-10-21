#pragma once
#include <cstddef>
#include <cstdint>
#include "elf.h"
#define ElfW(type) Elf64_##type
struct dl_phdr_info { uintptr_t dlpi_addr; const char* dlpi_name; const Elf64_Phdr* dlpi_phdr; unsigned short dlpi_phnum; };
int dl_iterate_phdr(int (*)(dl_phdr_info*,size_t,void*),void*);
