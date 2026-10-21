# Preservation provenance

This subtree was curated from the 2026-10-21 host assessment and reviewed source snapshots.
Source origins below are relative names used by that assessment; no runtime script reads the assessment directory.
The archive allowlist records SHA256 and byte count for each committed payload.

| Preserved component | Relative source origin | Curation |
|---|---|---|
| Native Steam desktop menu / pen / controller | `installation/`, `pen-steamui-bridge/`, `bluetooth-diagnostics/` | Custom repair source, focus guards, user unit, portable controller selection; no paired-device state |
| Decky / Mihomo | `proxy-install/`, `proxy-research/` | Custom lifecycle/compatibility fixes, secret-free templates, manual local subscription setup; no private bundle or subscription data |
| Desktop VRChat | `vr-diagnostics/launch_vrchat_known_route.py`, `known-working-route/`, `fex-build-plan/` | Private app FEX launcher, pinned build recipe, synthetic regression sources and bounded summary; no prefix/game/EAC binary |
| SteamVR runtime | `vr-diagnostics/steamvr-alvr/` and selected exact-profile proof | Portable wrappers, repeated-key FEX renderer, schema-checked ALVR settings payload, one-attempt retry gate |
| ALVR capture patches | `steamvr-alvr/headpose-metadata-review/`, `present-wait-alvr-v20.14.1-backport/` | Exact patches, verified source bases, host stubs, replay source and sanitized metadata; no core/raw stack/binary |
| Minimal layer build | `steamvr-alvr/pose-layer-build-source/`, `build_pose_capture_layer.py` | Small ALVR C++ closure; header fetch pinned by upstream commit and hashes; all outputs external |
| Android switch UI | `android-switch-app-deployed/` and selected diagnostic source | App/test/AIDL/XML/manifest and parameterized build recipe; no APK, signing key, PIN, or live boot action |
| UFS queue diagnostic | `ufs-diagnostics/`, reviewed installation continuation | Portable explicit sysfs read/write helper with private rollback record; volatile diagnostic only |

## Upstream code

- ALVR is `alvr-org/ALVR` v20.14.1, commit `a9f6542fa507a841f40ab4f3fcb531427cd02550`. Exact source, PR3357, and local pose-patch manifests live under `pcvr/patches/`, `pcvr/build/`, and `pcvr/licenses/`.
- Vulkan-Headers are pinned to v1.3.290, commit `b379292b2ab6df5771ba9870d53cf8b2c9295daf`. Fetch only the minimal include closure using the committed hash manifest. Their MIT/Apache license texts are retained.
- PicoJSON retains its BSD-2-Clause notice both in the header and in `pcvr/licenses/`.
- The private FEX build and regression sources keep their upstream lock and notices under `vrchat/`. Retain those notices when reusing them. The `build/evidence/eac-tests/tools/static-link.py` copy is byte-identical to `regressions/tools/static-link.py` so the preserved upstream README link remains usable.
- AOSP AIDL/interfaces copied for the Android helper retain their source and license information in that component's provenance. The app's private build/signing outputs stay local.
- Decky Loader and DeckyClash are obtained from their official releases at setup time. Their third-party bundles, dependencies, and Mihomo binary are not vendored here.

## Evidence policy

The current matrix records user-confirmed and runtime-confirmed observations without account or device identities.
Historical evidence is represented by a small result summary and exact source/fixture hashes where needed.
Raw logs, cores, screenshots, ELF/APK archives, and saved prefixes remain outside Git.
Do not replace a pending runtime check with the fact that a portable script passed local syntax or fixture tests.
