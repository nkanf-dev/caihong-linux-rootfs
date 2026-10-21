#include <fstream>
#include <iterator>
#define main existing_test_main
#include "test_pose.cpp"
#undef main
int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "Usage: %s EXTERNAL_UPDATE_FRAME_FIXTURE\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1], std::ios::binary);
    if (!in) { std::perror("external fixture"); return 2; }
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(in)), {});
    if (bytes.size() != 0x5620) {
        std::fputs("External fixture must contain exactly 22048 bytes\n", stderr);
        return 2;
    }
    const auto sp = reinterpret_cast<uintptr_t>(bytes.data());
    const auto bp = sp + 0x5610;
    TrackedDevicePose_t expected;
    std::memcpy(&expected, bytes.data() + 0x5e0, sizeof(expected));
    assert(check_pose(expected));
    assert(expected.bPoseIsValid == 1 && expected.bDeviceIsConnected == 1);
    // Saved Update frame: first array at RBP-0x5030, second at RBP-0x3c30.
    frames={{0,0,0,nullptr},{fake_base+0x285069,sp,bp,nullptr},{0,sp+bytes.size(),0,nullptr}};
    const auto recovered = find_pose_in_call_stack();
    assert(std::memcmp(&expected, &recovered, sizeof(expected)) == 0);
    TrackedDevicePose_t second;
    std::memcpy(&second, bytes.data() + 0x19e0, sizeof(second));
    assert(check_pose(second));
    assert(!same_matrix(recovered, second));
    assert(recovered.mDeviceToAbsoluteTracking.m[1][3] > 1.0f);
    std::printf("PASS actual saved-core replay: exact RBP-5030 HMD0 recovered; second prediction and controller records not selected. sizeof=%zu\n", sizeof(recovered));
}
