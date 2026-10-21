# Exact FEX build and staging recipe

## Source lock

| Item | Value |
| --- | --- |
| Repository | `https://github.com/StonkGuy/FEX.git` |
| Tag | `eac-2610.3` |
| Annotated tag object | `8b2b6d180c6c6f7a10b4dc1a68e4031dee575998` |
| Commit | `938eedfcd79eb00e86561fbdf4933770766f0ba9` |
| Maintainer recipe source | `StonkGuy/eac-arm64-emulation-poc`, commit `1dc6d0374573f41f1fe7ef0e4cb5a8fb9e5b68bc`, `scripts/steamos/build-fex.sh` |

`build/source-lock.json` contains the exact eight submodule commits. `build/container_build.py` checks HEAD, tag resolution, submodule pins, and clean trees before configuring. It never resets or cleans an existing checkout.

`upstream/build-fex-steam.sh` preserves the maintainer's Steam-mode flags and staging recipe. Use the resource-limited Python helper below for replay. The upstream global installer is intentionally absent.

## Native compiler environment

Run on the target Fedora 44 **aarch64 Linux system with 4 KiB pages**, as its non-root owner. `TUNE_CPU=native` must run on that device. Do not build this route on the Mac and expect the same CPU tuning.

Prepared image name:

```text
localhost/caihong-vrchat-fex-builder:fc44
```

The recorded Fedora 44 linux/arm64 base manifest is:

```text
sha256:d458dbabce9d9400db66c046ec07bec6b75759f85ea737b1e3235ef2b702f036
```

This identifies the base manifest. The compiler image also contains build packages. `build_fex.py` resolves that prepared local image to its immutable image ID, saves `logs/builder-image-lock.json`, and uses the ID with `--pull=never`. It rejects a changed image on replay. Keep the lock and an OCI export locally if exact compiler replay is required.

The original compiler-image ID and complete installed-RPM closure were not present in the supplied source-only recipe records. `evidence/compiler-provenance.json` preserves the base digest and Fedora release package references. Each new build records its actual RPM versions, compiler versions, image ID, CMake cache, and output hashes.

Required explicit packages inside the compiler image:

```text
clang lld cmake ninja-build git-core python3 python3-packaging
glibc-devel libstdc++-devel binutils gzip coreutils ca-certificates
```

For a future fresh rootless compiler container, install those packages **inside the container**, with weak dependencies disabled. `python3-packaging` is needed by the CPU-selection script. Then retain the resulting image as the local prepared image. Do not install compiler packages on the host for this route.

## Exact configuration

```text
-DCMAKE_BUILD_TYPE=Release
-DCMAKE_C_COMPILER=clang
-DCMAKE_CXX_COMPILER=clang++
-DBUILD_STEAM_SUPPORT=ON
-DBUILD_TESTING=OFF
-DBUILD_THUNKS=OFF
-DBUILD_FEXCONFIG=OFF
-DENABLE_LTO=OFF
-DENABLE_ASSERTIONS=OFF
-DTUNE_CPU=native
-DCMAKE_CXX_SCAN_FOR_MODULES=OFF
-DCMAKE_INSTALL_PREFIX=/usr
```

`BUILD_STEAM_SUPPORT` is the defined option in this pin. Do not substitute `ENABLE_STEAM_SUPPORT`.

Targets:

```text
FEX FEXBash FEXGetConfig FEXOfflineCompiler FEXServer FEXServerManager FEXpidof FEXCompatTool
```

Staging command:

```text
DESTDIR=/work/stage cmake --install /work/build-steam --component Runtime --strip
```

The stage contains seven native tools under `usr/bin/`, plus `FEXCompatTool`, `VERSIONS.txt`, `ConfigTemplate.json`, `emulator.json`, and `toolmanifest.vdf` at its root. Private assembly uses only the ten reviewed replacement files listed in [SETUP.md](SETUP.md); it preserves the original Armada integration files and thunks.

## Replay: build, inspect, synthetic tests

Keep the three helpers together in `build/`. On the device, from this directory:

```sh
python3 build/build_fex.py --work "$HOME/.local/share/caihong-vrchat-fex-build"
python3 build/validate_fex.py inspect --work "$HOME/.local/share/caihong-vrchat-fex-build"
python3 build/validate_fex.py compile-tests --work "$HOME/.local/share/caihong-vrchat-fex-build"
python3 build/validate_fex.py validate --work "$HOME/.local/share/caihong-vrchat-fex-build" --rootfs /usr/share/guestos/fex-mesa
python3 build/validate_fex.py suite --work "$HOME/.local/share/caihong-vrchat-fex-build" --rootfs /usr/share/guestos/fex-mesa
python3 build/validate_fex.py suite --work "$HOME/.local/share/caihong-vrchat-fex-build" --rootfs /usr/share/guestos/fex-mesa --inflated-environment
```

Inspect each phase's saved result before continuing. `/usr/share/guestos/fex-mesa` was the recorded stock x86-64 rootfs directory; explicitly select the actual existing rootfs. Do not change it or pass a squashfs file path.

Build limits: two jobs, 4 GiB memory, 6 GiB total memory+swap, 512 PIDs, and at least 20 GiB free throughout. The helper monitors free space and stops only its named container if that reserve is crossed. It sets no CPU quota because the recorded kernel lacked `cpu.max`.

The compiler container uses a read-only image and private work mount. It does not mount Steam. `/tmp` is an ephemeral container tmpfs, not a required scratch-file source. Build scripts do not install anything globally, launch games, or change Steam settings.

Validation runs on the host after compilation, so Podman's ptrace filters do not change test behavior. It checks AArch64 ELF headers and host-loader dependencies, uses the stock rootfs read-only, sets `FEX_PORTABLE=1` for guest re-exec, and selects a short unique private FEXServer data/socket path. Cleanup selects only that run's staged FEXServer; it never calls a global process kill.

The full table has 33 FEX cases, plus stock-rootfs `true` and the native ARM64 signal-mask reference, giving 35 recorded results. The historical outcome was 32 expected results; see [TESTING.md](TESTING.md).
