#pragma once
#include <cstdint>
#include <cstddef>
using unw_word_t = uintptr_t;
struct unw_context_t { int value; };
struct unw_cursor_t { unsigned frame; };
#define UNW_REG_IP 16
#define UNW_REG_SP 7
#define UNW_X86_64_RBP 6
int unw_getcontext(unw_context_t*);
int unw_init_local(unw_cursor_t*,unw_context_t*);
int unw_step(unw_cursor_t*);
int unw_get_reg(unw_cursor_t*,int,unw_word_t*);
int unw_get_proc_name(unw_cursor_t*,char*,size_t,unw_word_t*);
