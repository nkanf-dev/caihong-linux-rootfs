#!/usr/bin/env python3
"""Install only explicitly rendered app profiles while SteamVR is closed.

Back up both destinations. Never parse and reserialize repeated FEX keys.
"""
import argparse
import json
import os
import shutil
import stat
import time
from pathlib import Path
from paths import home, state_root
from retry_gate import check_closed

NAMES = ("server-fex-config.json", "vrcompositor.real.json", "vrmonitor.json")

def secure_ipc_dir(uid, base=Path("/tmp")):
    path = base / ("caihong-alvr-" + str(uid))
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("ALVR shared IPC directory must be a user-owned 0700 real directory")
    return path

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("rendered", type=Path)
    p.add_argument("--apply", action="store_true", help="Without this option, inspect only")
    a = p.parse_args()
    check_closed()
    uid = os.getuid()
    targets = {"server-fex-config.json": state_root() / "server-fex-config.json",
               "vrcompositor.real.json": home() / ".config/fex-emu/AppConfig/vrcompositor.real.json",
               "vrmonitor.json": home() / ".config/fex-emu/AppConfig/vrmonitor.json"}
    texts = {name: (a.rendered / name).read_text() for name in NAMES}
    for name, text in texts.items():
        json.loads(text)
        if '"HostEnv"' not in text:
            raise ValueError("Missing scoped HostEnv: " + name)
        if name != "vrmonitor.json" and "XDG_RUNTIME_DIR=/tmp/caihong-alvr-" + str(uid) not in text:
            raise ValueError("Wrong user's runtime profile: " + name)
        if name == "vrmonitor.json" and "LD_LIBRARY_PATH=" not in text:
            raise ValueError("Missing exact monitor loader path")
        if targets[name].is_symlink():
            raise ValueError("Refuse a symlink profile destination")
    if not a.apply:
        print("PASS: profiles parse; SteamVR is closed; no files installed")
        return
    secure_ipc_dir(uid)
    backup = state_root() / "backups" / ("profiles-" + time.strftime("%Y%m%dT%H%M%S"))
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {}
    for name, target in targets.items():
        existed = target.exists()
        if existed:
            shutil.copy2(target, backup / name)
        record[name] = {"destination": str(target), "existed": existed}
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".caihong-new")
        temp.write_text(texts[name])
        temp.chmod(0o600)
        temp.replace(target)
    (backup / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Installed three app profile files. Backup:", backup)

if __name__ == "__main__":
    main()
