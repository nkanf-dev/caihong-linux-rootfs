# Portable source-only ALVR capture-layer build

This directory retains the actual 16-source C++ compile/link recipe with portable inputs. The 37-file ALVR closure is 217,926 bytes. Vulkan headers are fetched into an external stage. No generated library or object file belongs in this checkout.

## Inputs and provenance

- `source/alvr/`: the pinned ALVR stable source closure, with the exact PR3357 six-file backport applied. `pose.cpp` stays at the original stable base in this immutable closure.
- `source-manifest.json`: original and staged Git blobs, SHA256 digests, patch names, and all 16 translation units.
- `vulkan-headers-manifest.json`: a pinned Vulkan-Headers commit, its 15-header include closure, three license files, Git blobs, sizes, and SHA256 digests.
- `fetch_vulkan_headers.py`: authenticated `gh api` exact-commit fetch and verification. `--from-dir` reuses an already downloaded exact closure. `--verify-only` checks a completed stage.
- `build_pose_capture_layer.py`: verifies inputs, copies sources into the external work directory, applies the exact reviewed head-pose patch, and compiles/links the layer there.
- `provenance.py`: shared integrity and external-output guards.

The manifests pin exact upstream commits. File-level hashes are checked again before staging or compiling. License texts and code-to-license mappings are in `../licenses/`.

## Prepare headers

Run from the repository root. Set `PCVR_WORK` to an external writable directory. GitHub CLI must be authenticated for the fetch route.

```sh
python3 postboot/pcvr/build/fetch_vulkan_headers.py --destination "$PCVR_WORK/Vulkan-Headers"
python3 postboot/pcvr/build/fetch_vulkan_headers.py --destination "$PCVR_WORK/Vulkan-Headers" --verify-only
```

For a verified existing local download:

```sh
python3 postboot/pcvr/build/fetch_vulkan_headers.py --from-dir "$EXISTING_VULKAN_HEADERS" --destination "$PCVR_WORK/Vulkan-Headers"
```

## Build in Linux x86_64

Required tools and development files: Python 3, Git, a C++17 compiler, libunwind, X11, and Xrandr. On Debian-family systems the development packages are `g++`, `libunwind-dev`, `libx11-dev`, and `libxrandr-dev`. Install them in the intended build environment.

Set `ALVR_SESSION_PATH` to the absolute Linux `session.json` path used by the target runtime. Use a fresh external work directory for each build.

```sh
python3 postboot/pcvr/build/build_pose_capture_layer.py --work-dir "$PCVR_WORK/build-dry" --headers-dir "$PCVR_WORK/Vulkan-Headers" --session-path "$ALVR_SESSION_PATH" --dry-run
python3 postboot/pcvr/build/build_pose_capture_layer.py --work-dir "$PCVR_WORK/build-release" --headers-dir "$PCVR_WORK/Vulkan-Headers" --session-path "$ALVR_SESSION_PATH" --compiler-command g++
```

`--compiler-command` accepts a quoted command with an optional explicit runner. For an already configured FEX guest toolchain, pass the runner and guest compiler as one quoted argument.

Output: `out/libalvr_vulkan_layer.so` and `out/build-result.json` in the external build directory. Temporary compiler files also stay there. The compile flags, hidden-export map, libunwind/dl link dependencies, and custom `ALVR_Negotiate` shim follow the source recipe. The shim uses the explicit session path instead of the official Rust filesystem resolver.

## Optional compositor main-task repair

Add `--main-comm` to either build command to include `../patches/main-comm/compositor_main_comm.h` and its guarded constructor in the negotiation shim. The build verifies every preserved input in that package, then substitutes the explicit session path into `ALVR_Negotiate.cpp.in`. The flag leaves pose, drawing, IPC and encoder source unchanged.

## Verification scope

Host preservation checks cover patch identity/application/reversal, source and license hashes, header fetch verification, corruption rejection, output boundaries, fixture hashes, unit tests, sanitizer tests, and build command staging. The preserved recipe does not install a layer or start a runtime. Runtime status belongs to the parent-owned PCVR status record.
