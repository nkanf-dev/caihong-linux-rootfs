# Current validation — 2026-10-21

This table records the latest reviewed state. Historical assessment checkpoints contain older stopped-run, black-screen, and 5 Mbps settings. Use this table and later reviewed amendments for recovery.

| Component | Observed result | Recovery boundary / next check |
|---|---|---|
| Linux desktop / KDE menu | Native Steam power menu exposes Switch to Desktop; persisted across a Steam session restart | Restore the scoped SteamUI setting; keep the native desktop session |
| Pen in SteamUI | User confirmed normal input; Gamescope-bound user service installed | Preserve focus/SteamUI guards; keep KDE's native tablet path |
| Xbox controller | Paired, connected, and trusted | Trust only the controller identified by the user; never ship its address |
| Decky / Mihomo | Native ARM64 Decky Loader 3.3.0; DeckyClash HK global/TUN/DNS/UDP path verified | Restore private subscription locally; keep control API on loopback |
| Steam download region | Hong Kong region 33 read back after session restart | Account country remains unchanged |
| Desktop VRChat | Login screen and EAC result 301 verified; later closed normally for PCVR work | x86_64 Proton Experimental plus private FEX eac-2610.3; no automatic login or world join |
| Private FEX synthetic tests | 32 of 35 expected results | Unresolved cases stay listed in the VRChat guide; private per-app scope |
| Full SteamVR + ALVR | SteamVR 2.17.10 and ALVR 20.14.1 delivered headset images; user confirmed fluid controller content | Retain original Valve compositor and reversible wrapper/layer backups |
| Present wait | Stock `steamvr.disableLinuxWaitForPresent=true` applied; exact PR3357 fallback patch validates | Build includes the six-file backport; keep the stock setting during the controlled check |
| ALVR pose capture | Exact-build layer compiled with guest x86_64 GCC16, deployed for one controlled check; user said head-turn delay was much improved | Partial user-verified pose improvement. A later dashboard error 203 is traced to the compositor process name; real main-task naming correction passed at 17:09; full dashboard/game checks pending |
| Stereo / dashboard | Right-eye UI fragments remain unresolved | Test both eyes separately after overlay crash review |
| Exact vrmonitor loader | Stock and distro loader-only probes resolve SteamVR/Qt libraries with a scoped HostEnv path | Monitor remained live without the Qt loader failure. Error 203 traced to its `/proc/PID/comm` compositor-name check; ALVR-only name correction set the real main task comm; same-run driver, VR_Init, and Ready passed at 17:09; error 203 gone |
| Official ARM64 client candidate | Isolated Background VR_Init returned 0 with a valid token using private resources/version links to the current x64 runtime | Component interoperability passed; no full native replacement or global VR_OVERRIDE; Steam library integration pending |
| Steam VR library | Guest Steam API connected in the 17:09 Ready run. The native ARM64 Steam VR main window/library integration is still absent; the official native client passed an isolated Background connection test | Do not treat guest Steam API success as native library-overlay success. Native Steam UI integration remains pending; no global override or full native runtime replacement was applied |
| Video queue | Balanced 10 Mbps setting read back; server queue 1, custom send buffer 65536, client buffer 1, weight 0.5 | 5 Mbps was an earlier experiment, not a permanent cap |
| Codec path | Host software x264; PICO hardware H264 decoder `c2.qti.avc.decoder` | Native Vulkan Video hardware encode absent. Iris module is loaded but no codec node was found |
| Audio / VRChat VR | Original EAC returned 301 at 17:11:33; `OpenVRLoader` started at 17:11:50, both controllers were detected, shared images reached SteamVR, and the game finished entering its configured private world at 17:12:24 | No credentials, login clicks, destination choice, or public-world join was performed by the agent. Headset visual confirmation, audio, and playability remain pending |
| UFS queue mitigation | Queue depth 63 → 16 temporarily; bounded game loading produced no new error in the recorded check | Diagnostic mitigation only; re-evaluate after reboot; never treat it as a persistent hardware repair |

## Runtime namespace contract

The server uses the stock Steam app-FEX path with app-specific `FEX_APP_CONFIG`.
The escaped compositor uses the distro FEX per-executable profile `AppConfig/vrcompositor.real.json`.
Both disable Vulkan and DRM thunks for full guest Vulkan.
Both need the same private shared IPC directory under `/tmp`; `/tmp` is only a runtime socket location, not a source dependency.

The inherited `XDG_RUNTIME_DIR` shadows an appended `Env` value in the actual loaders.
Use scoped `HostEnv` to replace that inherited key.
The compositor also replaces its inherited relative `GAMESCOPE_WAYLAND_DISPLAY` with the existing absolute endpoint.
Repeated `Env` and `HostEnv` keys are intentional FEX format. Do not round-trip these files through a dictionary serializer.

The harmless distro probe found a second detail: when the original inherited variable is absent, `putenv()` can add it to global `environ` without replacing the original `envp` pointer passed to the loader.
Therefore the profile check must use the real Steam inherited baseline and direct libc `getenv()`, not only a Python environment dictionary or an empty test environment.

## Acceptance checklist for the next authorized run

- [ ] Previous overlay fault reviewed offline; no stale SteamVR processes; clean retry receipt prepared.
- [ ] Same-run ALVR driver loaded; capture-to-encoder IPC connected.
- [ ] `ALVR_POSE_CAPTURE status=exact-build-hmd0`; finite matrix changes with head movement.
- [ ] Whole image tracks head turns without the previous lag or black edges.
- [ ] Both eyes show complete UI; dashboard opens without a crash.
- [ ] Native Steam VR library path works, or its remaining fault is recorded precisely.
- [ ] Audio works in both directions required by the user.
- [ ] VRChat enters VR through its normal EAC chain and renders a scene.

Root owns the live run and updates the result after review. The preservation work itself changes host repository files only.

## Dashboard error 203 follow-up

The monitor checks `/proc/PID/comm` for `vrcompositor`.
The official ALVR wrapper launches the preserved Valve executable as `vrcompositor.real`, whose Linux comm is truncated to `vrcompositor.re`.
The correction compiled with the target guest GCC and set the real main task name at 17:09:19; it does not patch the Valve monitor or create a fake process.
The exact-build pose path emitted a valid `exact-build-hmd0` matrix in the 17:00:30 run.
The same run loaded ALVR at 17:09:17.991 and reported `VR_Init successful` at 17:09:20.779.
Ready followed at 17:09:21; error 203 disappeared. A six-second sample reported about 79–83 ms total, 7–12 ms encode, 3 ms decode, 71 client FPS and 61–64 server FPS at 10 Mbps.
One VRChat VR launch was issued around 17:10 through the unchanged EAC route, private FEX, full x86_64 Proton, and the existing prefix.
The original EAC chain returned 301 during this VR run. VRChat initialized `OpenVRLoader`, detected both controllers, and submitted shared stereo images to SteamVR. The game then used its existing login and automatically entered the configured private world; the agent did not enter credentials, click login, select a destination, or join a public world. A six-second world sample had median server FPS 55, median encode time 13 ms, median hardware decode time 3 ms, and median total pipeline latency 85 ms. These are a short sample, not a playability pass. Luna directly viewed the headset screenshot: it shows VRChat in-world with settings UI in both eyes, without the earlier right-only dashboard gap in that frame. This does not establish all-time stereo correctness. User head-turn/controller acceptance, Steam dashboard integration, audio, and sustained world performance remain pending.

## Charging pause: prepared tools, not live acceptance

The user paused headset testing for charging. No headset wake, stream reconnect, Steam/game restart, or new runtime test is part of the following preparation. A later explicit request separately authorized disk-only inspection and selective removal of unused failed private runtimes.

- `pcvr/audio/`: a dynamic, namespace-preserving plan/apply/rollback helper with private transactional journals. Host tests cover disconnect, partial failure, reused endpoint IDs/owners, and new shared members. The earlier live routing attempt made no writes because the ALVR nodes disappeared; sound and microphone acceptance remain open.
- `pcvr/stereo/`: an offline compositor-profile candidate generator. It preserves repeated FEX keys and refuses all AppConfig output directories. `TU_DEBUG=flushall` is only a short same-scene diagnostic based on a related Mesa issue, not a confirmed or performance-safe repair. No candidate was installed.
- `pcvr/overlay/`: a read-only `IVRPaths_002` readiness-property query. Official ABI and exact native-client root-container evidence correct the earlier root-zero query. The corrected query has not passed a device test; it never dispatches a readiness URI or starts a runtime.
- A Steam VR/desktop convenience launcher is being prepared separately. Its source tests and cold-start design do not establish device acceptance. The existing manual desktop and VR routes remain the rollback baseline.

The previously verified native ARM64 client extension is installed as one architecture-specific file only. Native Steam library/overlay UI is still unverified. Do not report the four user issues as fixed by these host-only tools.

## Prepared Steam VR/desktop convenience entry

`launcher/` now preserves both real Steam choices through one app-scoped wrapper. Desktop forwards the original protected command with `--no-vr` and never creates a runtime backend. VR reuses a healthy existing runtime or admits one clean SteamVR start, then requires same-run ALVR loading, Ready, mapped driver, exact API version, and fresh decode/video events before the unchanged game command.

Both app 438100 and app 250820 launch-option templates are required because Steam may auto-start SteamVR first. The templates retain the verified EAC paths, WINEDEBUG/Xalia settings, AVPro argument, separate private FEX/prefix, and exact original launcher chain. An unexplained crash/safe-mode block stops rather than auto-clearing it. Receipt-generation and process-generation claims prevent duplicate starts; checked private dirfds protect local state.

Ninety mocked host tests and an independent adversarial review passed. This is source-preparation acceptance only. The new bundle and launch-option templates have NOT been deployed on the device; normal cold VR start, desktop start, close/reopen, healthy reuse, headset absence, audio and overlay must be checked after the charging pause. The core launcher does not yet auto-apply the separately prepared audio namespace route.

## Backup location update

The user chose to keep backups on the Mac rather than duplicate them on the tablet. Sixty-four historical runtime backup files were copied and individually size/SHA256-verified before device copies were removed. Original boot/recovery/GPT/AVB rescue assets were also consolidated locally. They live under `.local-artifacts/backups/`, mode 0700/0600, excluded by the local `.git/info/exclude` rule. No private backup bytes are tracked or pushed; a fresh clone does not contain them. Historical references to device backup paths describe the earlier checkpoint, not the current storage location.

## Prepared power-menu Android return

`power-menu/` is a source-only Decky plugin that preserves the native desktop action and proposes a separate “返回 Android” menu item and confirmation. It uses the existing Linux slot tool, explicit approved Android A/Linux B mapping, trusted config/tool digests, typed reboot preflight, single-use confirmation, independent slot readback, and normal inhibitor-aware reboot. No action runs on module load or cancellation. Installer/removal are scoped and digest-checked.

Host mock, frontend, typecheck, and build checks are recorded in its validation file. The source has not been installed on the tablet, and actual Decky/Steam shape, visible menu open/cancel, target boot-control/API readback, and Android boot remain deferred until the user resumes device testing. Do not treat source tests as a completed boot-switch acceptance.
