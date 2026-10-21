#!/usr/bin/env python3
"""Read a block queue depth, or apply/restore a reviewed volatile diagnostic.

Use on Linux with an explicitly identified whole-disk sysfs queue_depth file.
No filesystem, partition, boot, firmware, or persistent configuration is changed.
"""
import argparse
import json
import os
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("queue_depth", type=Path, help="Exact /sys/.../queue_depth file")
    p.add_argument("--set", type=int, dest="depth")
    p.add_argument("--record", type=Path)
    p.add_argument("--confirm-volatile-diagnostic", action="store_true")
    a = p.parse_args()
    path = a.queue_depth.resolve(strict=True)
    if not str(path).startswith("/sys/devices/") or path.name != "queue_depth":
        p.error("Expected an explicit /sys/devices/.../queue_depth path")
    before = int(path.read_text())
    if a.depth is None:
        print(json.dumps({"queue_depth": before, "persistent": False}))
        return
    if not a.confirm_volatile_diagnostic or a.record is None or not 1 <= a.depth <= 63:
        p.error("A write needs --confirm-volatile-diagnostic, --record, and depth 1..63")
    if a.record.exists():
        raise FileExistsError(a.record)
    record = {"sysfs_path": str(path), "before": before, "requested": a.depth,
              "persistent": False, "restore": before}
    a.record.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    a.record.write_text(json.dumps(record, indent=2) + "\n")
    a.record.chmod(0o600)
    path.write_text(str(a.depth) + "\n")
    record["after"] = int(path.read_text())
    a.record.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"before": before, "after": record["after"], "persistent": False}))

if __name__ == "__main__":
    main()
