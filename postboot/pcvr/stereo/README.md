# SteamVR right-eye geometry: controlled Turnip probe

Status: host-side proposal. Device tests are paused while the headset charges.
The next test must compare the same SteamVR controller scene before and after one change.
The existing clean VRChat capture contains different content and does not settle the SteamVR controller defect.

## Next probe: `TU_DEBUG=flushall`

Use only this variable for the first short comparison.
Apply it only to the FEX `vrcompositor.real` profile, then restart SteamVR under the root operator's control when the user is ready.
Keep the game, ALVR version, FFR, resolution, codec, bitrate, pose patch, present-wait setting, IPC, and monitor repairs unchanged.
Do not set it globally or add it to the game/server profile.

Mesa [issue 15792](https://gitlab.freedesktop.org/mesa/mesa/-/issues/15792) reports models falling apart or vanishing on a7xx.
Its Adreno 750 section reports that full `flushall` fixes that app's corruption while `syncdraw` does not.
The reporter narrowed the effect to per-draw `FD_CCU_CLEAN_COLOR` with `WAIT_FOR_ME` (`0x0202`).
That report uses another application on Android/KGSL; the present SteamVR route uses Linux/DRM.
It is a closely matched diagnostic lead, not a confirmed cause of this SteamVR defect.
The issue was open when retrieved on 2026-10-21. The related-MR API returned an empty list. No upstream fix commit was identified.

**Performance:** `flushall` cleans and invalidates caches before each draw, dispatch, blit, and related operation.
Expect lower FPS and higher latency. No numeric SteamVR cost is known.
The report's separate app fell from 60 to 15–18 FPS with full flushall on a725; even its narrower a750 mask fell from 54 to 33 FPS.
Use a short geometry comparison, then restore the original profile.
Do not keep this flag as a performance configuration.

## Exact source references

Official Mesa `mesa-26.2.4` resolves to commit `96cb43121031992b85767f9c1be8f3f48e22b1d2`.
This is a version-matched reference, not a verified source match for the saved custom ICD.

- [tu_util.cc L30–36](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_util.cc#L30-36): exact `nomultipos` and `flushall` tokens.
- [tu_cmd_buffer.cc L351–382](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_cmd_buffer.cc#L351-382): `TU_DEBUG(FLUSHALL)` adds all clean/invalidate bits; color clean/invalidate emits `FD_CCU_CLEAN_COLOR`.
- [tu_cmd_buffer.cc L8460–8463](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_cmd_buffer.cc#L8460-8463): flush in draw preparation.
- [tu_cmd_buffer.h L224–235](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_cmd_buffer.h#L224-235): named flag values.
- [tu_device.cc L77–110](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_device.cc#L77-110): `NOMULTIPOS` enters the shader-cache identity.
- [tu_shader.cc L3272–3273](https://gitlab.freedesktop.org/mesa/mesa/-/blob/96cb43121031992b85767f9c1be8f3f48e22b1d2/src/freedreno/vulkan/tu_shader.cc#L3272-3273): multiview lowering requires a vertex shader and a nonzero multiview mask.

No shader-cache purge is needed for `flushall`; it changes command emission.
No extra cache-disable variable is needed for `nomultipos`; it is in the cache identity.
Both require a process restart because Turnip reads startup settings when the driver initializes.

## Offline profile candidate generator

`stage_compositor_turnip_probe.py` reads an exported `vrcompositor.real.json`.
It creates a separate `*.candidate.json` and hash manifest.
It never edits its input, installs a profile, or starts/stops a process.
It refuses any `AppConfig` output ancestor, including case variants and lexical/resolved symlink paths.
This covers modern `fex-emu`, legacy `.fex-emu`, and an arbitrary `FEX_APP_CONFIG_LOCATION` root because FEX appends `AppConfig/` to that root.
It also refuses a non-candidate output name, an existing destination, or an existing `TU_DEBUG` assignment.
The candidate and manifest are private from creation; a failed manifest write removes only the new artifacts.
It preserves all existing bytes and repeated `Env`/`HostEnv` keys.
Do not parse and re-serialize an actual FEX profile with a normal JSON dictionary.

Generate from a private export; keep profiles and manifests outside the repository:

```sh
python3 postboot/pcvr/stereo/stage_compositor_turnip_probe.py \
  "$EXPORT_DIR/vrcompositor.real.json" \
  "$EXPORT_DIR/vrcompositor.real.flushall.candidate.json" \
  --mode flushall
python3 postboot/pcvr/stereo/test_stage_compositor_turnip_probe.py
```

`EXPORT_DIR` must point to the operator's private export directory.
The root operator must compare the candidate with the source before any later installation.
The only intended change is one additional `Config.HostEnv` assignment: `TU_DEBUG=flushall`.
Use `HostEnv` here because the existing runtime's inherited-variable override was previously tested with the FEX loaders.
The saved FEX source applies `HostEnv` with `putenv()` before constructing the guest ELF loader.
The full guest Mesa driver still reads its guest libc environment; verify effective guest `getenv("TU_DEBUG")` on the selected route at the next controlled start.
A host `/proc/PID/environ` check is useful evidence but does not by itself prove the guest's effective environment after FEX overrides.
If the variable already exists in an inherited launcher environment, retain its baseline value for rollback and verify which value the guest sees.

The optional `--mode nomultipos` creates a **separate**, mutually exclusive probe.
Do not combine it with `flushall`.
`nomultipos` disables Turnip's per-view-position optimization, not all stereo rendering.
It is only useful if the affected pipeline has a nonzero Vulkan multiview mask.
Ordinary sequential-eye or GS/`gl_Layer` stereo with `viewMask=0` does not use that lowering.
No evidence yet proves the affected SteamVR controller path uses Vulkan multiview.
Do not invent SteamVR `disableMultiview` or hidden-mesh settings.
The inspected Valve binary's `FACET_MULTIPASS` environment parser defaults to true, so setting it to 1 is not a justified change.

## A/B and rollback contract

1. Leave the running game unchanged during the charging pause.
2. When the user is ready, preserve the original compositor profile byte-for-byte and record its SHA256 outside the checkout.
3. Capture a fresh baseline of the SteamVR controller scene with both controllers visible. Keep the original headset image and ALVR pre-FFR `alvr_frame_input.ppm`.
4. Stop SteamVR normally. Root reviews and installs only the candidate for `vrcompositor.real`; no global FEX or game/server settings change.
5. Restart the same route. Verify effective `TU_DEBUG=flushall`, the same driver, and unchanged ALVR/FFR dimensions.
6. Capture the same SteamVR controller content again, including a fresh pre-FFR input. Compare controller surface continuity and dashboard completeness, not raw left/right pixel differences.
7. Restore the exact original compositor profile and verify its original SHA256. Restart once under root control to remove the debug flag.

Success requires the previously broken right-eye geometry to become complete in the same-content comparison.
A slower stream, a different VRChat image, a clean unrelated UI, or a single image with no controllers does not establish this result.
If full flushall has no visual effect, restore the baseline; do not stack more flags.
If it helps, preserve both captures and the actual driver identity before designing a lower-cost fix.

## Narrow source repair after a positive result

The reporter's a750 `CCU_CLEAN_COLOR | WAIT_FOR_ME` mask is a useful next source experiment.
A matched-source diagnostic can narrow the existing FLUSHALL branch to those named flags and retain the same one-variable gate.
This still flushes per draw and may be expensive. It is not an upstream fix or known optimal placement.
Identify the exact custom ICD source and reproduce its build first.
Do not patch arbitrary `0x16ff`/`0x17ff` constants in the binary or replace both native/guest drivers without evidence.
The current route requires the guest x64 ICD; it has Vulkan/DRM thunking disabled.
A native ARM64 replacement is a separate route and must not be changed as part of this test.

## Saved guest driver identity

The existing offline guest `libvulkan_freedreno.so` has:

- Embedded version string: `26.2.4`.
- GNU build ID: `d67dab4b9350e7bb8ab120ff740c84e7ad038216`.
- SHA256: `17e06fecc7aa59ccd699cad8ea90f574d392a8499a8bae8107fda4dff944e717`.
- Additional adjacent 40-hex rodata identifier: `920476b10efa3d98c9461e7328b45cfe48c167db`.

The additional identifier did not resolve to an official Mesa commit through GitLab or the authenticated GitHub mirror.
Mesa supports build-ID overrides, so do not label that string a source revision without further evidence.
The existing binary's strings include `flushall` and `nomultipos`.
These identities describe the saved guest library. Confirm the mapped runtime library at the later A/B start.
No large Mesa source archive, build, binary replacement, or device operation was done for this proposal.
