#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include "include/link.h"
#include "include/sys/prctl.h"
#include "include/sys/syscall.h"
#include <fcntl.h>
#include <unistd.h>
int fake_open(const char*,int,...);
ssize_t fake_read(int,void*,size_t);
ssize_t fake_write(int,const void*,size_t);
int fake_close(int);
pid_t fake_getpid();
int fake_syscall(int,...);
int fake_prctl(int,...);
#define open fake_open
#define read fake_read
#define write fake_write
#define close fake_close
#define getpid fake_getpid
#define syscall fake_syscall
#define prctl fake_prctl
#define constructor unused
#include "../compositor_main_comm.h"
#undef open
#undef read
#undef write
#undef close
#undef getpid
#undef syscall
#undef prctl
#undef constructor

bool use_build=true,wrong_module=false;
pid_t pid=500,tid=500;
const char* initial_comm="vrcompositor.re\n";
std::string last_write,last_path;
unsigned writes=0,prctls=0;
int fake_open(const char* path,int,...) { last_path=path;return 7; }
ssize_t fake_read(int,void* buf,size_t size) { auto n=std::strlen(initial_comm);assert(n<size);std::memcpy(buf,initial_comm,n);return n; }
ssize_t fake_write(int,const void* buf,size_t n) { last_write.assign(static_cast<const char*>(buf),n);++writes;return n; }
int fake_close(int) { return 0; }
pid_t fake_getpid() { return pid; }
int fake_syscall(int,...) { return tid; }
int fake_prctl(int,...) { ++prctls;return 0; }
int dl_iterate_phdr(int (*cb)(dl_phdr_info*,size_t,void*),void* out) {
    alignas(4) unsigned char note[36]={4,0,0,0,20,0,0,0,3,0,0,0,'G','N','U',0};
    std::memcpy(note+16,caihong_compositor_comm::expected_build_id,20);
    if(!use_build) note[16]^=1;
    Elf64_Phdr ph{};ph.p_type=PT_NOTE;ph.p_vaddr=reinterpret_cast<uintptr_t>(note);ph.p_memsz=36;
    dl_phdr_info info{};info.dlpi_name=wrong_module?"/usr/bin/FEX":"";info.dlpi_phdr=&ph;info.dlpi_phnum=1;
    return cb(&info,sizeof(info),out);
}
int main() {
    using caihong_compositor_comm::set_compositor_main_comm;
    set_compositor_main_comm();assert(prctls==1&&writes==0);
    tid=501;set_compositor_main_comm();assert(prctls==1&&writes==1&&last_write=="vrcompositor"&&last_path=="/proc/self/task/500/comm");
    initial_comm="vrcompositor\n";set_compositor_main_comm();assert(writes==2);
    initial_comm="vrserver\n";set_compositor_main_comm();assert(writes==2);
    initial_comm="FEX\n";set_compositor_main_comm();assert(writes==2);
    initial_comm="vrcompositor.re\n";use_build=false;set_compositor_main_comm();assert(writes==2);
    use_build=true;wrong_module=true;set_compositor_main_comm();assert(writes==2);
    std::puts("PASS production constructor: main prctl, worker main-task write, wrong comm/build/module all skipped");
}
