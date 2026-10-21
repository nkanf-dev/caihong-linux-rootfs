# ALVR patch preservation implementation plan

**Goal:** Keep the exact patch sources, host tests, and portable source-only build inputs.
**Architecture:** Store immutable patches and their base files. Stage fetched headers and patched build inputs in an external work directory. Compile the small layer through an explicit compiler command.
**Tech stack:** Python 3 standard library, Git, authenticated GitHub CLI, C++17.

## Files and steps

- [x] Preserve `patches/present-wait/{alvr-v20.14.1-pr3357.patch,upstream-pr3357.patch,manifest.json,verify_apply.py,base/}`. Verify all base hashes, then run check/apply/reverse checks in a temporary tree.
- [x] Preserve `patches/headpose/{alvr-v20.14.1-exact-compositor-pose.patch,original/,patched/,manifest.json}` and `tests/pose/{test_pose.cpp,include/,replay_exact_update.cpp,replay-metadata.json}`. Compile unit and sanitizer tests outside the checkout. Require an explicit external replay fixture and verify its hash.
- [x] Preserve `build/source/alvr/` without Vulkan headers. Create compact source/header hash manifests, `fetch_vulkan_headers.py`, and a portable `build_pose_capture_layer.py` that stages in an external work directory.
- [x] Preserve upstream license texts in `licenses/`, including ALVR MIT, embedded picojson BSD, and Vulkan-Headers license files. Map copied code to pinned upstream paths and licenses.
- [x] Add host-only verification tests for patch identities, source manifests, external-output restrictions, fixture handling, fetch verification, and dry-run build planning. Run `python3 -m unittest discover -s postboot/pcvr/tests/pose -p 'test_*.py'` from the checkout.
- [x] Inspect the owned paths for binaries, raw memory, absolute host dependencies, and whitespace errors. Report files and checks to the parent. Do not commit or run device/live commands.
