#pragma once
#include <cstdint>
#define PT_NOTE 4
#define NT_GNU_BUILD_ID 3
struct Elf64_Nhdr { uint32_t n_namesz, n_descsz, n_type; };
struct Elf64_Phdr { uint32_t p_type,p_flags; uint64_t p_offset,p_vaddr,p_paddr,p_filesz,p_memsz,p_align; };
