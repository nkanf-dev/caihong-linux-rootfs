# VRChat Steam dual-mode launcher

This bundle keeps Steam's own two VRChat choices:

- **VRChat** starts the VR route.
- **in Desktop (Non-VR) Mode** passes the original `--no-vr` argument.

The recorded Windows entries both use the original `launch.exe`. The sanitized
[source fixture](steam-launch-choices.json) records their arguments and source URL.
Do not append `--no-vr` to the shared launch options. Steam adds it only for the
desktop choice.

## What the launcher does

Desktop mode calls the preserved private VRChat launcher once. It never constructs
the VR runtime backend, contacts ALVR, starts SteamVR, or changes an audio route.
The existing private x64 prefix and protected Proton/FEX/EAC chain stay in use.

VR mode waits for a healthy runtime or starts SteamVR once through native Steam.
SteamVR loads its already registered ALVR driver. The ALVR dashboard GUI is not
started: its own auto-launch path can clear safe mode, which bypasses this gate.
The wrapper never modifies the game, EAC, Valve executables, ALVR binaries, global
FEX options, headset trust, accounts, or worlds.

The readiness gate requires all of these:

1. One live server, real compositor, and monitor owned by the desktop user.
2. Same-run server and monitor startup PIDs and timestamps in `FEX.txt` or
   `FEX.previous.txt`, successful ALVR driver loading, and monitor Ready.
3. The ALVR driver mapped in that live server.
4. ALVR API version `20.14.1` at loopback port 8082.
5. Newly received stream statistics with positive video packet rate and FPS,
   plus positive decode timing and client/server FPS in graph statistics.
   Both samples must be fresh. A saved `Streaming` session enum cannot pass.

A trusted headset must already be configured. Open ALVR on it and wear it.
A sleeping or disconnected headset stops the launch after a bounded deadline.
The gate does not wake, install, trust, log in, or launch a world on the headset.

## Install the bundle and print the two launch options

Run from this source checkout as the desktop user:

```sh
python3 postboot/launcher/install.py
python3 postboot/launcher/install.py --apply
```

The first command previews the transaction. The second copies the source-only
bundle to `~/.local/lib/caihong-vrchat-launcher/`, records backups, and prints
launch options with this user's actual HOME safely quoted. It does not change
Steam configuration. Set the two printed lines in Steam Properties:

- App **438100 / VRChat** uses `dual_mode.py --mode auto -- %command%`.
- App **250820 / SteamVR** uses `steamvr_auto.py -- %command%` and the existing
  per-app FEX profile and guest Turnip ICD.

Install **both** lines. Steam can automatically start app 250820 before it runs
app 438100's command. `steamvr_auto.py` admits that normal clean start itself;
VRChat then waits for the same startup instead of starting a second instance.
If VRChat enters first, the SteamVR entry uses its still-pending receipt.

Keep the existing runtime profiles, driver registration, private FEX tool,
private `cvrc-x64` prefix, compositor wrapper, and capture layer in place. This
installer does not recreate those prerequisites. See [PCVR setup](../pcvr/README.md)
and the [protected VRChat route](../vrchat/README.md).

The install command accepts `--steamvr-vk-driver` when the reviewed guest ICD has
another path. Do not substitute the native ARM64 ICD for the guest x64 one.
The SteamVR wrapper preserves its existing full stock-FEX route, scoped loader
escape, exact compositor rule, and private IPC directory creation at boot.
The game still uses its separate private FEX tool and short prefix.

## Clean start and fault recovery

A normal clean start writes one 10-minute receipt automatically, only when:

- SteamVR and VRChat are fully closed.
- No crash marker exists.
- `driver_alvr_server.blocked_by_safe_mode` is explicitly `false`.
- No previous launcher failure requires review.

The original SteamVR wrapper consumes that receipt once. A pending valid receipt
is reused without extending its lifetime. No restart loop runs. The launcher
never stops an existing game or runtime, clears a marker, or unblocks a driver.
A runtime already starting is observed until the deadline, not restarted.

A crash, safe-mode block, stale receipt, PID change, or failed gate stops with a
fixed diagnostic. Review the status and existing runtime logs. Close the runtime
normally before using the existing reviewed retry procedure:

```sh
python3 "$HOME/.local/lib/caihong-vrchat-launcher/runtime/retry_gate.py" \
  --prepare --fault-reviewed \
  --evidence "$HOME/.local/state/caihong-pcvr/reviewed-failure.md"
```

That separate gate backs up the settings and crash marker. It clears only ALVR's
safe-mode block after a real review. The automatic launcher does none of those
recovery writes. Keep the evidence file private. After inspection, retire an
expired receipt deliberately rather than renewing it automatically.

Status and clean-start evidence live under
`~/.local/state/caihong-vrchat-launcher/` with directory mode 0700 and file mode
0600. The runtime receipt stays under `~/.local/state/caihong-pcvr/`. No full argv,
environment, session, headset identity, or account data is copied into status.
Existing Steam/ALVR logs retain their normal private local role.

## Roll back

Save the launch options that were present before installation. Restore those two
lines through Steam Properties first. Preview the recorded source-file rollback,
then apply it:

```sh
python3 postboot/launcher/install.py --rollback <transaction-manifest>
python3 postboot/launcher/install.py --rollback <transaction-manifest> --apply
```

Rollback restores a destination only if its current digest still matches the
installed file. It removes a new file only when that transaction says it was
previously absent. It does not stop processes, edit Steam VDF files, remove
prefixes, reset game data, or delete runtime evidence.

## Host tests and device acceptance

```sh
python3 -m unittest discover -s postboot/launcher/tests -v
```

Tests use fake clocks, fake runtimes, filesystem fixtures, and local protocol
fixtures. Current work is host-only source preparation. Device operations remain
paused while the headset charges.

The charged-device acceptance sequence is: desktop choice; fully closed cold VR
choice; healthy runtime reuse; normal close and reopen; headset absent; reviewed
fault gate; then game audio, microphone, both eyes, and dashboard/library overlay.
Game audio, microphone, right-eye UI, and native Steam overlay remain separate
acceptance items. This core launcher does not apply audio routes. The optional
[namespace routing helper](../pcvr/audio/route_namespace.py) has its own
`plan`, `apply`, and journaled `rollback` API. Do not route unrelated desktop apps.
