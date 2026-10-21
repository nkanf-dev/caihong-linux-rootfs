#!/usr/bin/env python3
"""Preserve Valve's ARM64 launch chain and set only the native loader path."""
import json
import os
import sys
import time
from pathlib import Path
from paths import library_paths, steam_root, state_root
from retry_gate import consume_receipt
from install_profiles import secure_ipc_dir

def prepare(args, env):
    steam = steam_root()
    if not args or args[0] != str(steam / "linuxarm64/steam-launch-wrapper"):
        raise ValueError("Expected the original Steam launch wrapper")
    if env.get("SteamAppId") != "250820":
        raise ValueError("This wrapper is only for SteamVR app 250820")
    if args.count(str(steam / "steamapps/common/FEX-Emu/fex-compat-tool")) != 1:
        raise ValueError("Expected exactly one stock FEX compat tool")
    startup = str(steam / "steamapps/common/SteamVR/bin/vrstartup.sh")
    indices = [i for i, arg in enumerate(args) if arg == startup]
    if len(indices) != 1:
        raise ValueError("Expected exactly one original vrstartup.sh")
    paths = [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p]
    paths += [p for p in library_paths()[2:] if Path(p).is_dir()]
    if "/usr/lib64" not in paths:
        raise ValueError("The native /usr/lib64 loader path is absent")
    env["SYSTEM_LD_LIBRARY_PATH"] = ":".join(dict.fromkeys(library_paths()[:2] + paths))
    result = list(args)
    index = indices[0]
    result[index:index] = [sys.executable, str(Path(__file__).with_name("steamvr_inner_runtime.py"))]
    return result, env

def main():
    args, env = prepare(sys.argv[1:], dict(os.environ))
    secure_ipc_dir(os.getuid())
    consume_receipt()
    state = state_root()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = {"time": time.time(), "appid": 250820,
              "guest_ld_library_path_unchanged": True,
              "original_command_chain_preserved": True}
    (state / "runtime-launch.json").write_text(json.dumps(record, indent=2) + "\n")
    os.execve(args[0], args, env)

if __name__ == "__main__":
    main()
