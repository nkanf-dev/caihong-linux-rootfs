#!/usr/bin/env python3
"""Render app-scoped FEX profiles; do not install or launch anything.

FEX string-array options use repeated keys. Keep their raw text intact.
"""
import argparse
import json
import os
from pathlib import Path

def pairs(items):
    return ",\n".join("      " + json.dumps(k) + ": " + json.dumps(v) for k, v in items)

def render(home, uid, gamescope_display="gamescope-0", steam=None, alvr=None):
    home = Path(home).expanduser().resolve()
    steam = Path(steam).expanduser().resolve() if steam else home / ".local/share/Steam"
    alvr = Path(alvr).expanduser().resolve() if alvr else home / ".local/share/caihong-steamvr-alvr-20.14.1/alvr_streamer_linux"
    runtime = "/tmp/caihong-alvr-" + str(uid)
    old_runtime = "/run/user/" + str(uid)
    display = gamescope_display if gamescope_display.startswith("/") else old_runtime + "/" + gamescope_display
    server = "{\n  \"Config\": {},\n  \"ThunksDB\": {\"Vulkan\": 0, \"drm\": 0},\n  \"AppOverrides\": {\n    \"vrserver\": {\n".replace('\"','"')
    server += pairs([("HostEnv", "XDG_RUNTIME_DIR=" + runtime),
                     ("Env", "PIPEWIRE_RUNTIME_DIR=" + old_runtime)])
    monitor_lib = str(steam / "steamapps/common/SteamVR/bin/linux64") + ":" + str(steam / "steamapps/common/SteamVR/bin/linux64/qt/lib") + ":/usr/lib"
    server += '\n    },\n    "vrmonitor": {\n' + pairs([("HostEnv", "LD_LIBRARY_PATH=" + monitor_lib)])
    server += "\n    }\n  }\n}\n"
    lib = "/usr/lib:" + str(steam / "steamapps/common/SteamVR/bin/linux64") + ":" + str(steam / "steamapps/common/SteamVR/bin/linux64/qt/lib")
    compositor = '{\n  "Config": {\n' + pairs([
        ("HostEnv", "XDG_RUNTIME_DIR=" + runtime),
        ("HostEnv", "GAMESCOPE_WAYLAND_DISPLAY=" + display),
        ("Env", "PIPEWIRE_RUNTIME_DIR=" + old_runtime),
        ("Env", "PULSE_RUNTIME_PATH=" + old_runtime + "/pulse"),
        ("Env", "LD_PRELOAD=" + str(alvr / "libexec/alvr/alvr_drm_lease_shim.so")),
        ("Env", "ALVR_SESSION_JSON=" + str(home / ".config/alvr/session.json")),
        ("Env", "LD_LIBRARY_PATH=" + lib)])
    compositor += '\n  },\n  "ThunksDB": {"Vulkan": 0, "drm": 0}\n}\n'
    monitor = '{\n  "Config": {\n' + pairs([("HostEnv", "LD_LIBRARY_PATH=" + monitor_lib)]) + '\n  }\n}\n'
    return {"server-fex-config.json": server, "vrcompositor.real.json": compositor, "vrmonitor.json": monitor}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--home", type=Path, default=Path.home())
    p.add_argument("--uid", type=int, default=os.getuid())
    p.add_argument("--steam-root", type=Path)
    p.add_argument("--alvr-root", type=Path)
    p.add_argument("--gamescope-display", required=True, help="Existing endpoint from the Steam session")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.uid < 1:
        p.error("Use the desktop user's UID")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, text in render(args.home, args.uid, args.gamescope_display, args.steam_root, args.alvr_root).items():
        json.loads(text)  # Syntax only. Never reserialize this parsed dictionary.
        path = args.output / name
        if path.exists():
            raise FileExistsError(path)
        path.write_text(text)
        path.chmod(0o600)
        print(name)

if __name__ == "__main__":
    main()
