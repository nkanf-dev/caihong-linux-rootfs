# Full SteamVR 2.17.10 + ALVR 20.14.1 recovery

Read [current validation](../docs/current-validation.md) before changing the installed runtime.
Use native ARM64 Steam and the existing Valve launch chain. This recovery keeps SteamVR app 250820 scoped to its own configuration.

## 1. Preserve the installed state

Close SteamVR and the ALVR dashboard normally.
Keep a private backup of these exact files and record hashes before replacing anything:

- `~/.local/share/Steam/config/steamvr.vrsettings` and any `vrserver_crash_timestamp.txt`.
- `~/.config/openvr/openvrpaths.vrpath` and `~/.config/alvr/session.json`.
- `~/.config/fex-emu/AppConfig/vrcompositor.real.json`, if present.
- The server's app-specific FEX profile and SteamVR launch options.
- `SteamVR/bin/linux64/vrcompositor`, its original regular file, and the ALVR capture layer.

The ALVR session contains client identities. Keep it private and never add it to Git.
The known original Valve compositor SHA256 is `a642dc897b934c9e73e500c1029871e99e5eb13de5c7052b980ef4277e84ab30`.
GNU build ID for the exact pose path is `f5c560dcaa16d7b2625ece684b02396505e0768f`.
If the installed Valve binary differs, stop and review the new build before using exact offsets.

## 2. Obtain the matching official runtime

Use Steam app 250820 for SteamVR. The recorded installed build is 25330290 / version 2.17.10.
Obtain matching official ALVR v20.14.1 streamer and Android client assets from `alvr-org/ALVR`.
Use authenticated `gh release view` / `gh release download` for GitHub metadata and release assets.
Recorded release digests:

| Asset | Bytes | SHA256 |
|---|---:|---|
| `alvr_streamer_linux.tar.gz` | 58079521 | `be82b4a7a3cb3607dd5c307cf2b0a1b524d1ecbba586d657a458117a8a63bc09` |
| `alvr_client_android.apk` | 20936003 | `be68feeb02665e3d69f1cdbcabf38ea4d15c42868a7ec6b5e698dbefee4e4e36` |

Keep downloads outside this checkout. Trust only the headset identified by the user through ALVR's official client-management API. Do not enable automatic trust or copy an old client hostname, serial, or private address.
USB was used for installation/diagnostics; actual streaming uses the LAN.

Register the private ALVR driver through the official dashboard/SteamVR driver path.
The private layout used by the templates is `~/.local/share/caihong-steamvr-alvr-20.14.1/alvr_streamer_linux`.
The official compositor wrapper is `libexec/alvr/vrcompositor-wrapper`; the official DRM lease shim is `libexec/alvr/alvr_drm_lease_shim.so`.
Keep the original `vrcompositor` as `vrcompositor.real`, then point `vrcompositor` to the official wrapper only after checking the original hash and the wrapper's exact target. Record this transaction for rollback.
Do not replace or patch Valve's real executable.

## 3. Render and install the narrow FEX profiles

The renderer uses the current user's HOME and UID.
Pass the **existing** Gamescope display endpoint from the Steam session. Do not guess another display.

```sh
python3 postboot/pcvr/profiles/render_profiles.py \
  --gamescope-display gamescope-0 \
  --output "$HOME/.local/state/caihong-pcvr/rendered-profiles"
python3 postboot/pcvr/runtime/install_profiles.py \
  "$HOME/.local/state/caihong-pcvr/rendered-profiles"
# Review both files first. This next command writes only the three app profile files.
python3 postboot/pcvr/runtime/install_profiles.py \
  "$HOME/.local/state/caihong-pcvr/rendered-profiles" --apply
```

The generated server profile is `~/.local/state/caihong-pcvr/server-fex-config.json`.
The compositor profile uses `~/.config/fex-emu/AppConfig/vrcompositor.real.json`.
The exact monitor rule is also rendered into stock `AppOverrides.vrmonitor` and distro `AppConfig/vrmonitor.json`, with `HostEnv=LD_LIBRARY_PATH=<SteamVR/bin/linux64>:<qt/lib>:/usr/lib`.
Both loader probes passed. The monitor stayed live in the later run; the guarded ALVR-only main-task name correction later removed error 203 and reached Ready.
Do not merge these two mechanisms or change global FEX settings.

`HostEnv=XDG_RUNTIME_DIR=/tmp/caihong-alvr-<uid>` replaces the inherited runtime key for just the two FEX targets.
This 0700 user-owned directory gives the layer and encoder the same `alvr-ipc` pathname across their runtime mount views.
The compositor also replaces its inherited Gamescope endpoint with the existing absolute path.
`PIPEWIRE_RUNTIME_DIR` and `PULSE_RUNTIME_PATH` retain the original audio endpoint.
The inherited baseline matters: see the direct-libc `getenv()` detail in current validation.

Both profiles use full guest Vulkan/DRM (`ThunksDB` Vulkan=0, drm=0).
The compositor keeps the proven guest library path `/usr/lib:.../SteamVR/bin/linux64:.../qt/lib`.
Do not substitute the ARM64 native loader path for this guest path.
Repeated FEX keys must stay repeated. `json.loads()` is suitable for syntax checking only; `json.dumps(json.loads(profile))` destroys entries.

## 4. Keep the Valve runtime wrappers together

Copy the complete `runtime/` directory to a stable location, for example `~/.local/lib/caihong-pcvr/runtime/`.
The two wrappers set only `SYSTEM_LD_LIBRARY_PATH` for the native ARM64 runtime.
They leave initial guest `LD_LIBRARY_PATH` under Valve vrenv/Scout control and preserve the original command chain.
The outer wrapper inserts the inner one immediately before the existing `vrstartup.sh`.

Set SteamVR's app launch options through Steam, using the actual home path expanded locally:

```text
env FEX_APP_CONFIG=<HOME>/.local/state/caihong-pcvr/server-fex-config.json VK_DRIVER_FILES=/usr/share/vulkan/icd.d/freedreno_icd.x86_64.json python3 <HOME>/.local/lib/caihong-pcvr/runtime/steamvr_runtime_escape.py %command%
```

`<HOME>` is a placeholder, not a literal path. Keep `VK_DRIVER_FILES` aligned with the installed guest Turnip ICD. The recorded device used Adreno 750.
The wrapper enforces app 250820 and one stock FEX compat tool. It also consumes one clean-retry receipt.

## 5. Configure capture and latency

Keep `steamvr.disableLinuxWaitForPresent=true` in `steamvr.vrsettings` during the checked route.
The source backport for ALVR PR3357 is preserved under `patches/`; use its verifier and exact manifests before applying it.
The exact-build image-pose repair and its build/test instructions are also preserved there.
For the current recovered route, include the guarded `patches/main-comm/` repair with the build recipe’s `--main-comm` flag. It preserves the actual compositor main task name expected by the unmodified Valve monitor; it does not create another process.
Build only the capture layer; keep the official ALVR driver, encoder, client, IPC packet format, timestamps, and Valve executable unchanged.

Use `profiles/alvr-conservative-video.json` and `profiles/alvr-balanced-10mbps.json` as settings-only safe profiles.
Generate a payload against the **local** 20.14.1 session schema:

```sh
python3 postboot/pcvr/runtime/alvr_profile_request.py \
  postboot/pcvr/profiles/alvr-balanced-10mbps.json \
  --session "$HOME/.config/alvr/session.json" \
  --output "$HOME/.local/state/caihong-pcvr/balanced-request.json"
```

Review and send this settings-only payload through the official ALVR dashboard API/UI.
Use a local loopback dashboard endpoint; never include client identities in the request file.
Read back every changed field. Reconnect the stream after queue/socket/client-buffer changes.
Current balanced settings are 10 Mbps, server queue 1, send buffer Custom 65536, client buffer 1, and history weight 0.5.
There is no hard 5 Mbps limit. Earlier 5 Mbps/queue-2 experiments are superseded.

## 6. Mandatory clean retry gate

A compositor/dashboard fault stops the run. Inspect the saved failure before starting another run.
Do not clear safe mode while any old SteamVR process exists. Do not run restart loops.

Create a short private text file that records the reviewed failure and the one proposed correction.
The gate backs up settings and a well-formed crash marker, clears only ALVR's safe-mode block when needed, and issues one 10-minute receipt.
It does not stop or start a process.

```sh
python3 "$HOME/.local/lib/caihong-pcvr/runtime/retry_gate.py"
python3 "$HOME/.local/lib/caihong-pcvr/runtime/retry_gate.py" \
  --prepare --fault-reviewed --evidence "$HOME/.local/state/caihong-pcvr/reviewed-failure.md"
```

Launch once from Steam after this check. The outer wrapper consumes the receipt before it executes the original chain.
A failed run needs a new review and receipt. Never interpret a cleared marker as a successful stream.

For the controlled pose check, require same-run ALVR loading, IPC connection, and finite changing `status=exact-build-hmd0` output before asking for a short headset check.
Review both eyes and Steam dashboard separately. The guarded main-task name correction removed error 203; right-eye UI, full dashboard acceptance, and Steam library integration still need checks.

## Rollback

1. Close SteamVR and the dashboard normally. Verify no old processes remain.
2. Restore SteamVR launch options and the three profile files from the private transaction backups. Remove a profile only when the backup manifest says it was originally absent.
3. Restore the original ALVR capture layer from the exact backup. Check its hash before replacing the patched file.
4. For the compositor wrapper, remove `vrcompositor` only if it is still the symlink to the expected private ALVR wrapper. Rename the verified `vrcompositor.real` back to `vrcompositor`.
5. Restore `steamvr.vrsettings`, OpenVR registration, and ALVR session from their own backups if those settings are being reverted. Keep headset identities private.
6. Keep crash evidence, reviewed-failure notes, and backups outside Git. Retire any unused retry receipt.

Do not delete the shared IPC directory while either endpoint is running.
The portable wrappers/profile renderer were checked locally with fixtures. Root owns deployment and the runtime result recorded in current validation.

## Native ARM64 Steam integration candidate

`profiles/native-steamos-arm64-candidate.json` preserves the official package URL, two matching independent hash references, and selected ARM64 client metadata.
The 571 MB package and its shared libraries are not in this repository.
It remains a candidate-only source record; an isolated Background VR_Init check passed with a valid token and private resource/version links to the current x64 runtime.
Native Steam VR library integration remains separate work.
Do not replace the installed SteamVR or global OpenVR paths from this manifest.
