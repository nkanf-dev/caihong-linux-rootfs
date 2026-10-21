#!/usr/bin/env python3
"""Refresh digests for existing allowlisted files only. New paths need review."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "postboot/archive-allowlist.json"
manifest = json.loads(path.read_text())
for record in manifest["files"]:
    file = root / record["path"]
    if file.is_symlink() or not file.is_file():
        raise ValueError("Missing or symlinked allowlisted source: " + record["path"])
    data = file.read_bytes()
    record["bytes"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
path.write_text(json.dumps(manifest, indent=2) + "\n")
print("Refreshed", len(manifest["files"]), "existing allowlist records; no new paths admitted")
