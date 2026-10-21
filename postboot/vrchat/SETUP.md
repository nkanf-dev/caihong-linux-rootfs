# Setup: private desktop route

These steps describe the preserved route. Run target-side steps only when you intend to configure the device. The repository preservation and its host tests do not run them.

## 1. Keep a rollback point

1. Close VRChat and other Steam games normally.
2. Record VRChat's existing Steam compatibility-tool choice and launch options in a private owner-controlled note.
3. Keep any existing prefix backup. Do not copy account configuration into this repository.
4. Leave the stock FEX tool and original prefix in place.

The historical x86-64 first-run evaluator touched the original prefix after it was backed up. Treat that backup as a distinct rollback asset; do not label the original prefix untouched.

## 2. Install the normal Steam components

The verified components were:

| Component | Exact identifier |
| --- | --- |
| VRChat | Steam app `438100` |
| Steam FEX tool | Steam app `3127680` |
| Full x86-64 Proton Experimental | Steam app `1493710`, internal tool name `proton_experimental` |
| Required x86-64 runtime | Steam app `4183110` |
| Proton EasyAntiCheat Runtime | Steam tool `Proton EasyAntiCheat Runtime` |

Historical Proton version: `experimental-11.0-20261014-x86_64`.

Select the full x86-64 Proton tool for VRChat. The hyphenated alias `proton-experimental` resolved to the ARM64 family during the assessment and was discarded. Match the registered internal name and Steam tool app, not only a similar display label.

## 3. Build and inspect a private stage

Follow [BUILD.md](BUILD.md). Keep source, build products, and stage under:

```text
$HOME/.local/share/caihong-vrchat-fex-build
```

Run the native dependency inspection and synthetic tests before assembling the private tool. The preserved historical run has three unresolved synthetic differences; retain its per-app scope.

## 4. Assemble only the private tool

Run as the non-root owner. No Steam game may be using the private copy while its files change. The following commands require a fresh destination; stop if it already exists.

```sh
stock="$HOME/.local/share/Steam/steamapps/common/FEX-Emu"
private="$HOME/.local/share/caihong-vrchat-fex-eac-tool"
stage="$HOME/.local/share/caihong-vrchat-fex-build/stage"
test -d "$stock" && test ! -e "$private"
```

Continue only after the last check succeeds:

```sh
cp -a "$stock" "$private"
cp "$stage/usr/bin/FEX" "$stage/usr/bin/FEXBash" \
   "$stage/usr/bin/FEXGetConfig" "$stage/usr/bin/FEXOfflineCompiler" \
   "$stage/usr/bin/FEXServer" "$stage/usr/bin/FEXServerManager" \
   "$stage/usr/bin/FEXpidof" "$private/usr/bin/"
cp "$stage/FEXCompatTool" "$stage/VERSIONS.txt" \
   "$stage/ConfigTemplate.json" "$private/"
```

Only those ten files come from the stage. Keep the private copy's original Armada `fex-compat-tool`, `emulator.json`, `toolmanifest.vdf`, host thunks, and guest thunks. Check each copied file against the stage with `cmp` or SHA-256 before launch. Do not run the upstream global `install-fex-tool.sh` or overlay the entire stage onto Steam's stock tool.

The private copy is a runtime artifact. Keep it on the device, outside this repository. It does not need global compatibility-tool registration; the launcher substitutes its wrapper in the existing Steam chain.

## 5. Install the launcher

From this directory on the device:

```sh
install -d -m 700 "$HOME/.local/bin"
install -m 700 launch_vrchat_known_route.py "$HOME/.local/bin/launch-vrchat-known-route.py"
mkdir -p "$HOME/.local/share/cvrc-x64"
```

The fresh short prefix is for full x86-64 Proton. Do not transplant an ARM64 prefix or add the old Mono `RuntimePath` override. Proton initializes its contents on first launch.

The launcher requires an owner-only `XDG_RUNTIME_DIR` or `/run/user/<uid>`. It uses `cvrc-fex/data/` beneath that directory for the private FEXServer socket. The complete socket path must be shorter than 108 bytes. Do not use a long prefix path as the server-data path.

## 6. Set VRChat launch options

Use Steam's VRChat properties. Keep the full x86-64 Proton selection. Paste this as **one line**:

```sh
env STEAM_COMPAT_DATA_PATH="$HOME/.local/share/cvrc-x64" EAC_LAUNCHERDIR="$HOME/.local/share/cvrc-x64/pfx/drive_c/users/steamuser/AppData/Roaming/EasyAntiCheat" PROTON_EAC_RUNTIME="$HOME/.local/share/Steam/steamapps/common/Proton EasyAntiCheat Runtime" WINEDEBUG=-all PROTON_USE_XALIA=0 python3 "$HOME/.local/bin/launch-vrchat-known-route.py" %command% --no-vr --enable-avpro-in-proton
```

`--no-vr` is part of the verified desktop route. `PROTON_LOG` and `PROTON_LOG_DIR` are removed by the launcher. Leave `FEX_NEEDSSECCOMP`, `FEX_HIDEHYPERVISORBIT`, and `FEX_HOSTFEATURES` unset; the launcher rejects nonempty values. Do not add the unrelated Asahi topology or GPU-memory settings from public examples to this preserved baseline.

## 7. Verify one desktop launch

Start VRChat from Steam. Keep its original `launch.exe` and normal EAC path. Check for the login screen and normal input. Stop there unless the owner chooses to log in. Close the game normally before SteamVR work.

The launcher writes only a mode-0600 route-preparation record to `$HOME/.local/state/caihong-vrchat-logs/x64-known-route/launch-routing.json`. It stores no argument list or inherited environment. That record does not report game or EAC success.

## 8. Authorized VR-attempt delta

A later authorized attempt removed only `--no-vr` from the launch-options line above. It kept the same full x86-64 Proton, private pinned FEX, normal EAC chain, and `--enable-avpro-in-proton`. Validation was pending at this preservation checkpoint.

To return to the verified desktop route, restore `--no-vr`. Headset output, tracking, controllers, microphone, playback, and streaming remain open validation items. Account login and world join were not performed.
