# Exact-compositor head-pose source patch

`alvr-v20.14.1-exact-compositor-pose.patch`, `original/`, and `patched/` preserve the reviewed one-file patch and exact before/after source bytes. The stable pose header is also retained for host tests. This local patch is separate from upstream PR3353.

`manifest.json` records the stable base, source/patch digests, compositor ELF build ID, PC ranges, and HMD-array offset. The known Update frame selects array element zero at RBP minus `0x5030`. The second prediction array is left alone. Other matching frames require one unambiguous pose matrix. The patch checks finite values, rotation, frame bounds, and unwind errors.

Use `../../tests/pose/run_tests.py` for host unit tests and explicit external saved-frame replay. The full layer recipe is in `../../build/README.md`. The source license is `../../licenses/ALVR-vulkan-layer-MIT.txt`.

The unit tests replace libunwind and ELF module discovery with deterministic stubs. Device-side unwind and frame capture are checked separately during a runtime test.
