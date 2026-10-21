#!/usr/bin/env python3
"""Stage the pinned minimal Vulkan-Headers closure outside the checkout."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

from provenance import external_path, load_manifest, relative_path, verify_record, verify_tree


def stage(destination, source=None, verify_only=False):
    manifest = load_manifest("vulkan-headers-manifest.json")
    destination = external_path(destination)
    if verify_only:
        verify_tree(destination, manifest["files"])
        return destination
    if source:
        source = Path(source).resolve()
        verify_tree(source, manifest["files"])
    else:
        subprocess.run(["gh", "auth", "status", "--hostname", "github.com"], check=True)
    destination.mkdir(parents=True, exist_ok=True)
    for record in manifest["files"]:
        rel = relative_path(record["path"])
        target = destination / rel
        if target.is_symlink() or destination not in target.resolve().parents:
            raise ValueError("Unsafe stage file: " + str(target))
        if target.exists():
            verify_record(target.read_bytes(), record)
            continue
        if source:
            data = (source / rel).read_bytes()
        else:
            endpoint = ("repos/" + manifest["repository"] + "/contents/" +
                        record["path"] + "?ref=" + manifest["commit"])
            response = subprocess.run(["gh", "api", endpoint], check=True,
                                      capture_output=True, text=True)
            payload = json.loads(response.stdout)
            if (payload.get("type") != "file" or payload.get("encoding") != "base64" or
                    payload.get("sha") != record["git_blob"] or
                    payload.get("path") != record["path"]):
                raise ValueError("Unexpected GitHub metadata: " + record["path"])
            data = base64.b64decode(payload["content"].replace("\n", ""), validate=True)
        verify_record(data, record)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
        print("VERIFIED", record["path"], flush=True)
    verify_tree(destination, manifest["files"])
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--from-dir", type=Path, help="Copy an already downloaded exact closure after verifying every file")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only and args.from_dir:
        parser.error("--verify-only cannot be combined with --from-dir")
    root = stage(args.destination, args.from_dir, args.verify_only)
    print("PASS: pinned Vulkan-Headers closure:", root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
