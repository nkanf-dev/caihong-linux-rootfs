#!/usr/bin/env python3
"""Check or repair one already-paired controller; never scan, pair, or store its address."""
import argparse
import json
import re
import subprocess


def state(address):
    result = subprocess.run(["bluetoothctl", "info", address], capture_output=True,
                            text=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeError("Controller info failed; check Bluetooth locally")
    return {key.lower(): bool(re.search(r"^\s*" + key + r": yes\s*$", result.stdout, re.M))
            for key in ("Paired", "Trusted", "Connected")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "repair", "untrust"))
    parser.add_argument("address", help="paired controller address; not saved or printed")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", args.address):
        parser.error("Use the address of one already-paired controller")
    before = state(args.address)
    if not before["paired"]:
        raise RuntimeError("Controller is not paired; pair it in Bluetooth settings first")
    commands = ("trust", "connect") if args.action == "repair" else (("untrust",) if args.action == "untrust" else ())
    for command in commands:
        result = subprocess.run(["bluetoothctl", command, args.address], capture_output=True,
                                text=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("Controller action failed; inspect Bluetooth settings locally")
    after = state(args.address)
    print(json.dumps({"before": before, "after": after}, sort_keys=True))
    if args.action == "repair" and not (after["trusted"] and after["connected"]):
        raise RuntimeError("Controller did not reach trusted and connected state")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as error:
        # Do not print subprocess output, which can contain local device identifiers.
        raise SystemExit("Controller check/action failed: " + (str(error) if isinstance(error, RuntimeError) else type(error).__name__))
