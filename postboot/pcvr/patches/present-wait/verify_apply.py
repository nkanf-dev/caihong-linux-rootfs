#!/usr/bin/env python3
"""Verify/apply the exact ALVR v20.14.1 PR3357 six-file patch. No downloads/build/install."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("source_root", type=Path)
parser.add_argument("--apply", action="store_true", help="Apply after validating all six official base blobs")
args = parser.parse_args()
here = Path(__file__).resolve().parent
manifest = json.loads((here / "manifest.json").read_text())
patch = here / "alvr-v20.14.1-pr3357.patch"
assert hashlib.sha256(patch.read_bytes()).hexdigest() == manifest["minimal_patch_sha256"], "patch digest differs"

def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

for rec in manifest["files"]:
    data = (args.source_root / rec["path"]).read_bytes()
    assert git_blob(data) == rec["base_git_blob"], "not official unpatched v20.14.1: " + rec["path"]
subprocess.run(["git", "apply", "--check", str(patch)], cwd=args.source_root, check=True)
print("PASS: six official v20.14.1 base blobs; git apply --check")
if args.apply:
    subprocess.run(["git", "apply", str(patch)], cwd=args.source_root, check=True)
    for rec in manifest["files"]:
        data = (args.source_root / rec["path"]).read_bytes()
        assert git_blob(data) == rec["expected_fixed_git_blob"], "patched blob differs: " + rec["path"]
    print("PASS: applied files exactly match all six upstream fixed blobs")
