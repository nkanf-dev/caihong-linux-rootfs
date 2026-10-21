#!/usr/bin/env python3
"""Restore native loader search paths after Valve enters pressure-vessel."""
import os
import sys
from paths import library_paths, steam_root

def prepare(args, env):
    expected = str(steam_root() / "steamapps/common/SteamVR/bin/vrstartup.sh")
    if not args or args[0] != expected:
        raise ValueError("Expected Valve vrstartup.sh")
    if env.get("SteamAppId") != "250820" or not env.get("PRESSURE_VESSEL_RUNTIME"):
        raise ValueError("Must run inside SteamVR's Valve runtime")
    env["SYSTEM_LD_LIBRARY_PATH"] = ":".join(library_paths())
    return args, env

def main():
    args, env = prepare(sys.argv[1:], dict(os.environ))
    os.execve(args[0], args, env)

if __name__ == "__main__":
    main()
