#define CAIHONG_COMM_TEST
#include "../compositor_main_comm.h"
#include <cassert>
#include <string>
#include <vector>
using namespace caihong_compositor_comm;
int prctl(int,...) { return 0; }
int dl_iterate_phdr(int (*)(dl_phdr_info*,size_t,void*),void*) { return 0; }
int main() {
    assert(basename_is("/some/path/vrcompositor.real",25,"vrcompositor.real")==false); // supplied truncated size
    const std::string path="/some/path/vrcompositor.real";
    assert(basename_is(path.data(),path.size(),"vrcompositor.real"));
    alignas(4) unsigned char note[36]={4,0,0,0,20,0,0,0,3,0,0,0,'G','N','U',0};
    std::memcpy(note+16,expected_build_id,20);assert(exact_build_note(note,36));
    assert(!exact_build_note(note,35));note[16]^=1;assert(!exact_build_note(note,36));note[16]^=1;
    Elf64_Phdr ph{};ph.p_type=PT_NOTE;ph.p_vaddr=reinterpret_cast<uintptr_t>(note);ph.p_memsz=36;
    dl_phdr_info info{};info.dlpi_addr=0;info.dlpi_phdr=&ph;info.dlpi_phnum=1;
    bool matched=false;info.dlpi_name="";assert(find_exact_main(&info,0,&matched)==1&&matched);
    matched=false;info.dlpi_name="/usr/bin/FEX";assert(find_exact_main(&info,0,&matched)==0&&!matched);
    info.dlpi_name="/SteamVR/vrcompositor.real";assert(find_exact_main(&info,0,&matched)==1&&matched);
    assert(rename_main_task(123,123));
    std::puts("PASS: exact module basename, wrong process/build rejection, ELF note bounds, main-thread route");
}
