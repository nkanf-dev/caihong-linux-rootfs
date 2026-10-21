# Native Steam VR overlay: prepared existing-session query

Status: preparation only. Headset charging paused device tests before the corrected query was run.
This directory does not start Steam, SteamVR, a game, or an overlay. It never sends a URI or writes a path property.

## Verified component and remaining gate

The official SteamOS ARM64 `vrclient.so` passed an isolated Background client connection against the existing x64 SteamVR server when it used that server's real resources and version metadata.
Only the architecture extension `SteamVR/bin/linuxarm64/vrclient.so` was then installed with a rollback record.
No x64 file, native API loader, resource, version file, global `VR_OVERRIDE`, or runtime service was replaced.
The existing native Steam UI still had no VR main window or mutual capabilities. Component interoperability is not overlay acceptance.

The old query used root container zero and returned `TrackedProp_InvalidDevice` (5). It did not read a readiness value.
The corrected root container is `0x600000000`, established by the inspected native client's property-container constructor and multiple `ReadPathBatch` call sites.
The corrected root has not passed a device test.

## Source contract

- Official API source: <https://github.com/ValveSoftware/openvr/blob/0924064316de3effbcd1acf1e309182a2deb1c05/headers/openvr_capi.h>
- Exact interface: `FnTable:IVRPaths_002` (availability was observed on the candidate native client).
- Read batch is slot 0; StringToHandle is slot 2. No C++ `this` argument is used for the flat table.
- `PathRead_t` is 40 bytes on the intended ARM64 ABI: offsets 0, 8, 16, 20, 24, 28, 32.
- String property tag is 5. Batch and per-property errors must both be zero.
- The only queried property is `/steam/vr_connection_ready`.

The helper initializes one `VRApplication_Background` client only if an existing `vrserver` is found, then shuts down only its own client.
It does not call `StartVR`, `QuitAllVR`, or an app launch URI.
It uses the current user's native library path supplied by the operator; do not supply an x64 shared library to native Python.

## Host tests

```sh
python3 -B -m unittest discover -s postboot/pcvr/overlay -p 'test_*.py' -v
```

These are mocked ABI/privacy tests, not a native runtime or Steam UI test.

## Resume after charging

Run only as the normal desktop user after checking that the existing server is healthy:

```sh
install -d -m 700 "$HOME/.local/state/caihong-pcvr/overlay-query"
python3 postboot/pcvr/overlay/read_native_steam_readiness.py   "$HOME/.local/share/Steam/steamrtarm64/libopenvr_api.so"   "$HOME/.local/state/caihong-pcvr/overlay-query/ready-value.once"
```

The output file must not exist. It is created exclusively with mode 0600 in a private caller-owned directory.
Never print, copy into reports, or commit the value. The path-property suffix may be sensitive.
If the interface, type, container, length, encoding, or error check fails, stop and inspect the public status. Do not dispatch an empty or invented URI.

The installed Valve server/dashboard has an existing-session `steam://vr_connection_ready/` notification route, but this tool does not send it.
A later operator-owned single notification needs the actual current value and must verify that the game/server PIDs remain unchanged, that native Steam creates a VR main window, that mutual capabilities load, and that the headset shows the Steam library.
Do not use `steam://run/250820` or `StartVR(true)` as a harmless refresh while a game is running.

## Rollback

This helper has no persistent runtime configuration. Remove only its private output file when no longer needed.
The standard native client extension has a separate installation backup/receipt; remove it only if it was originally absent and its hash still matches the verified candidate.
Do not remove or replace any x64 runtime or the working capture layer.
