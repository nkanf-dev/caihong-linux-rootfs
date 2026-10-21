#include <cassert>
#include <cstring>
#include <limits>
#include <vector>
#include <cstdio>
#include "../../patches/headpose/patched/alvr/vulkan_layer/util/pose.hpp"
#include "include/link.h"
#include "include/libunwind.h"

struct Frame { uintptr_t ip,sp,bp; const char* name; };
std::vector<Frame> frames;
bool fail_context=false, fail_frame=false;
uintptr_t fake_base=0x10000000;
int unw_getcontext(unw_context_t*) { return fail_context ? -1 : 0; }
int unw_init_local(unw_cursor_t* c,unw_context_t*) { c->frame=0; return 0; }
int unw_step(unw_cursor_t* c) { ++c->frame; return c->frame<frames.size() ? 1 : 0; }
int unw_get_reg(unw_cursor_t* c,int reg,unw_word_t* out) {
    if(fail_frame && reg==UNW_REG_SP) return -1;
    auto& f=frames.at(c->frame);
    *out=reg==UNW_REG_IP ? f.ip : reg==UNW_REG_SP ? f.sp : f.bp;return 0;
}
int unw_get_proc_name(unw_cursor_t* c,char* out,size_t n,unw_word_t*) {
    const char* name=frames.at(c->frame).name;
    if(!name) return -1;
    std::strncpy(out,name,n);return 0;
}
int dl_iterate_phdr(int (*cb)(dl_phdr_info*,size_t,void*),void* out) {
    alignas(4) static unsigned char note[36]={
        4,0,0,0,20,0,0,0,3,0,0,0,'G','N','U',0,
        0xf5,0xc5,0x60,0xdc,0xaa,0x16,0xd7,0xb2,0x62,0x5e,
        0xce,0x68,0x4b,0x02,0x39,0x65,0x05,0xe0,0x76,0x8f};
    Elf64_Phdr ph{};ph.p_type=PT_NOTE;ph.p_vaddr=reinterpret_cast<uintptr_t>(note)-fake_base;ph.p_memsz=sizeof(note);
    dl_phdr_info info{};info.dlpi_addr=fake_base;info.dlpi_phdr=&ph;info.dlpi_phnum=1;
    return cb(&info,sizeof(info),out);
}
#include "../../patches/headpose/patched/alvr/vulkan_layer/util/pose.cpp"

TrackedDevicePose_t valid_pose(float x=0) {
    TrackedDevicePose_t p{};
    p.mDeviceToAbsoluteTracking.m[0][0]=1;p.mDeviceToAbsoluteTracking.m[1][1]=1;p.mDeviceToAbsoluteTracking.m[2][2]=1;
    p.mDeviceToAbsoluteTracking.m[0][3]=x;
    p.eTrackingResult=200;p.bPoseIsValid=1;p.bDeviceIsConnected=1;return p;
}
int main() {
    static_assert(sizeof(TrackedDevicePose_t)==80);
    auto p=valid_pose();assert(check_pose(p));
    auto bad=p;bad.mDeviceToAbsoluteTracking.m[0][0]=std::numeric_limits<float>::quiet_NaN();assert(!check_pose(bad));
    bad=p;bad.mDeviceToAbsoluteTracking.m[1][3]=std::numeric_limits<float>::infinity();assert(!check_pose(bad));
    bad=p;bad.vVelocity.v[0]=std::numeric_limits<float>::infinity();assert(!check_pose(bad));
    bad=p;bad.mDeviceToAbsoluteTracking.m[0][0]=-1;assert(!check_pose(bad));
    bad=p;bad.bPoseIsValid=0;assert(!check_pose(bad));
    alignas(8) unsigned char note[36]={4,0,0,0,20,0,0,0,3,0,0,0,'G','N','U',0};
    std::memcpy(note+16,compositor_build_id,20);assert(has_build_id(note,36));
    note[16]^=1;assert(!has_build_id(note,36));assert(!has_build_id(note,15));
    assert(!has_build_id(note,34));
    std::vector<unsigned char> bytes(512);auto begin=reinterpret_cast<uintptr_t>(bytes.data());
    assert(!scan_frame(begin,begin+bytes.size()).candidates);
    assert(!scan_frame(begin,begin+79).candidates);
    assert(!scan_frame(begin,begin-1).candidates);
    assert(!scan_frame(begin,begin+maximum_frame_bytes+1).candidates);
    std::memcpy(bytes.data()+4,&p,sizeof(p));auto found=scan_frame(begin,begin+bytes.size());assert(found.candidates==1&&!found.ambiguous&&found.offset==4);
    std::memcpy(bytes.data()+164,&p,sizeof(p));found=scan_frame(begin,begin+bytes.size());assert(found.candidates==2&&!found.ambiguous);
    auto other=valid_pose(2);std::memcpy(bytes.data()+164,&other,sizeof(other));found=scan_frame(begin,begin+bytes.size());assert(found.candidates==2&&found.ambiguous);
    // Known Update slot selects HMD zero, not either controller or second prediction.
    for(int iteration=0;iteration<2;++iteration) {
        std::vector<unsigned char> stack(0x55e0+iteration*16);
        auto sp=reinterpret_cast<uintptr_t>(stack.data());auto bp=sp+0x55c0;
        p=valid_pose(float(iteration+1));
        std::memcpy(reinterpret_cast<void*>(bp-0x5030),&p,sizeof(p));
        other=valid_pose(99);std::memcpy(reinterpret_cast<void*>(bp-0x5030+80),&other,sizeof(other));
        std::memcpy(reinterpret_cast<void*>(bp-0x3c30),&other,sizeof(other));
        frames={{0,0,0,nullptr},{fake_base+0x285069,sp,bp,nullptr},{0,bp+16,0,nullptr}};
        auto selected=find_pose_in_call_stack();assert(same_matrix(selected,p));
        bad=p;bad.bPoseIsValid=0;std::memcpy(reinterpret_cast<void*>(bp-0x5030),&bad,sizeof(bad));
        selected=find_pose_in_call_stack();assert(selected.bPoseIsValid==0);
        fail_frame=true;assert(find_pose_in_call_stack().bPoseIsValid==0);fail_frame=false;
    }
    // Async refuses ambiguous device poses rather than choosing a controller.
    frames={{0,0,0,nullptr},{fake_base+0x281000,begin,begin+400,nullptr},{0,begin+bytes.size(),0,nullptr}};
    assert(find_pose_in_call_stack().bPoseIsValid==0);
    frames={{0,0,0,nullptr},{fake_base+0x2840000,begin,0,nullptr},{0,begin+bytes.size(),0,nullptr}};
    assert(find_pose_in_call_stack().bPoseIsValid==0);
    fail_context=true;assert(find_pose_in_call_stack().bPoseIsValid==0);fail_context=false;
    std::puts("PASS: finite/rotation/build-ID/bounds/ambiguity/HMD-index0/moved-stack/unwind-failure");
    return 0;
}
