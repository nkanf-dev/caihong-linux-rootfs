#!/usr/bin/env python3
"""Prepare a single SteamVR attempt after the previous fault was reviewed.

No process is stopped or launched. Default mode is read-only.
"""
import argparse
import json
import os
import shutil
import stat
import time
from pathlib import Path
from paths import home, state_root, steam_root

PROCESS_NAMES = ("vrserver", "vrcompositor", "vrmonitor", "vrstartup", "vrwebhelper", "vrdashboard")

def active_processes(proc=Path("/proc")):
    if not proc.is_dir():
        raise RuntimeError("Linux /proc is required for the runtime gate")
    active = []
    for path in proc.iterdir():
        if not path.name.isdecimal() or int(path.name) == os.getpid():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            argv = [raw.decode(errors="replace") for raw in path.joinpath("cmdline").read_bytes().split(b"\0") if raw]
            names = [path.joinpath("comm").read_text().strip()]
            if argv:
                names.append(Path(argv[0]).name)
                if names[-1] in ("FEX", "FEXInterpreter") and len(argv) > 1:
                    names.append(Path(argv[1]).name)
            if any(name == n or name.startswith(n + ".") for name in names for n in PROCESS_NAMES):
                active.append(int(path.name))
        except OSError:
            continue
    return sorted(active)

def check_closed(proc=Path("/proc")):
    active = active_processes(proc)
    if active:
        raise RuntimeError("Close SteamVR normally before retry; active PIDs: " + ", ".join(map(str, active)))

def prepare_retry(settings, state, *, fault_reviewed, evidence_path):
    if not fault_reviewed or not evidence_path.is_file():
        raise ValueError("Record the reviewed failure in a local text file first")
    if settings.is_symlink() or not settings.is_file():
        raise ValueError("Expected a regular SteamVR settings file")
    data = json.loads(settings.read_text())
    marker = settings.with_name("vrserver_crash_timestamp.txt")
    if marker.exists() and (marker.is_symlink() or not all(p.isdecimal() for p in marker.read_text().split()) or len(marker.read_text().split()) != 3):
        raise ValueError("Unexpected crash marker; inspect it manually")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = state / "backups" / time.strftime("%Y%m%dT%H%M%S")
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copy2(settings, backup / settings.name)
    blocked = data.get("driver_alvr_server", {}).get("blocked_by_safe_mode")
    if marker.exists():
        marker.rename(backup / marker.name)
    if blocked is True:
        data["driver_alvr_server"]["blocked_by_safe_mode"] = False
        temporary = settings.with_name(settings.name + ".caihong-new")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.chmod(stat.S_IMODE(settings.stat().st_mode))
        temporary.replace(settings)
    receipt = {"created_at": time.time(), "appid": 250820, "attempts": 1,
               "backup": str(backup), "fault_review": str(evidence_path.resolve()),
               "safe_mode_was_blocked": blocked, "automatic_restart": False}
    output = state / "retry-receipt.json"
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    output.chmod(0o600)
    return receipt

def consume_receipt(state=None, now=None):
    state = state or state_root()
    path = state / "retry-receipt.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Run retry_gate.py --prepare for one reviewed attempt first")
    receipt = json.loads(path.read_text())
    age = (time.time() if now is None else now) - receipt["created_at"]
    if receipt.get("attempts") != 1 or receipt.get("appid") != 250820 or not 0 <= age <= 600:
        raise RuntimeError("Retry receipt is invalid or older than 10 minutes")
    check_closed()
    path.rename(state / "retry-receipt-consumed.json")
    return receipt

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--fault-reviewed", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    check_closed()
    settings = steam_root() / "config/steamvr.vrsettings"
    data = json.loads(settings.read_text())
    if args.prepare:
        if args.evidence is None:
            parser.error("--evidence is required for --prepare")
        record = prepare_retry(settings, state_root(), fault_reviewed=args.fault_reviewed,
                               evidence_path=args.evidence)
        print(json.dumps(record, indent=2))
    else:
        print(json.dumps({"closed": True, "blocked_by_safe_mode": data.get("driver_alvr_server", {}).get("blocked_by_safe_mode"),
                          "crash_marker_present": settings.with_name("vrserver_crash_timestamp.txt").exists(),
                          "prepared": False}, indent=2))

if __name__ == "__main__":
    main()
