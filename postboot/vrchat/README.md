# VRChat private FEX route

This directory preserves the VRChat desktop route verified on the Caihong Fedora 44 aarch64 system on 2026-10-21.

## Verified result

The unchanged Steam → `launch.exe` → Easy Anti-Cheat → VRChat chain reached the **Create an Account or Log In** screen. EAC returned **301: Easy Anti-Cheat successfully loaded in-game**. The game was later closed normally to continue SteamVR work.

- **Desktop:** login screen and a mouse-input probe verified.
- **Account login and world join:** not performed.
- **VR headset, controllers, streaming, and audio:** not yet validated by this route.
- **Synthetic FEX suite:** 32 of 35 results matched expectations. Three differences remain; see [TESTING.md](TESTING.md).

`evidence/SUCCESS.json` and `evidence/CHECKPOINT.json` are small historical records. They are not live process monitors.

A later authorized VR attempt removed only `--no-vr`. It kept the full x86-64 Proton/private FEX/EAC route. Validation was pending at this preservation checkpoint; see `evidence/VR-ATTEMPT.json`. Restore `--no-vr` for the known desktop baseline.

## Route

```text
ARM64 Steam
  → original Armada game launcher
  → private copy of Steam FEX, using StonkGuy/FEX eac-2610.3
  → full x86-64 Proton Experimental
  → original VRChat launch.exe
  → stock Proton EasyAntiCheat Runtime
  → VRChat desktop (--no-vr)
```

The private launcher changes exactly one stock `fex-compat-tool` argument to the private wrapper. It then calls `/usr/libexec/armada/armada-game-launch` with the rest of Steam's arguments intact.

The stock/global FEX tool stays in place. Game and EAC executables stay unchanged. The private prefix and the short private FEXServer socket isolate this route from other games.

## Files

| Path | Purpose |
| --- | --- |
| `launch_vrchat_known_route.py` | Actual private-route launcher, adapted to HOME and the current UID. |
| `SETUP.md` | Private-only build, assembly, and Steam setup. |
| `ROLLBACK.md` | Return VRChat to its prior Steam settings without a global replacement. |
| `BUILD.md` | Exact source/submodule pins, compiler-image provenance, flags, and staging contract. |
| `TESTING.md` | Historical 32/35 summary and host-only checks for this preservation. |
| `build/` | Build/stage and synthetic-validation helpers. |
| `regressions/` | Five small upstream synthetic programs, build scripts, and a tiny linker fallback. |
| `upstream/build-fex-steam.sh` | Pinned maintainer Steam-mode build reference; stage only. |
| `evidence/` | Sanitized historical result records and source provenance. |

No runtime binary, prefix, core dump, account data, private network configuration, or raw game log is stored here. These files have no dependency on the assessment scratch directory.

## Host-only checks

From this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_launcher build/test_recipe.py test_preservation
```

The launcher tests mock `execv`. They do not start Steam, a game, EAC, or a device connection.
