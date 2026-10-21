#!/usr/bin/env python3
"""Compile deterministic pose tests; optionally replay a verified external fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PCVR = HERE.parents[1]
REPOSITORY = next((parent for parent in PCVR.parents if (parent / ".git").exists()), PCVR)


def external_path(value):
    path = Path(value).expanduser().resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("Test output/fixture must be outside the repository: " + str(path))
    return path


def verify_fixture(value):
    path = external_path(value)
    metadata = json.loads((HERE / "replay-metadata.json").read_text())
    data = path.read_bytes()
    if len(data) != metadata["fixture_bytes"] or hashlib.sha256(data).hexdigest() != metadata["fixture_sha256"]:
        raise ValueError("External saved-frame fixture size/SHA256 differs from replay-metadata.json")
    return path


def run(output, compiler, sanitizers=False, fixture=None):
    output = external_path(output)
    output.mkdir(parents=True, exist_ok=True)
    flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror"]
    flags += (["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
              if sanitizers else ["-O2"])
    flags += ["-I" + str(HERE / "include"),
              "-I" + str(PCVR / "patches/headpose/patched/alvr/vulkan_layer/util")]
    programs = [("test_pose.cpp", [])]
    if fixture is not None:
        fixture = verify_fixture(fixture)
        programs.append(("replay_exact_update.cpp", [str(fixture)]))
    for filename, arguments in programs:
        binary = output / (Path(filename).stem + ("-sanitized" if sanitizers else ""))
        command = compiler + flags + [str(HERE / filename), "-o", str(binary)]
        print("COMPILE", shlex.join(command), flush=True)
        subprocess.run(command, check=True)
        subprocess.run([str(binary)] + arguments, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compiler-command", default="clang++")
    parser.add_argument("--sanitizers", action="store_true")
    parser.add_argument("--fixture", type=Path, help="Explicit external fixture for saved-core replay; hash checked before compile")
    args = parser.parse_args()
    compiler = shlex.split(args.compiler_command)
    if not compiler:
        parser.error("Compiler command must not be empty")
    if args.output_dir:
        run(args.output_dir, compiler, args.sanitizers, args.fixture)
    else:
        with tempfile.TemporaryDirectory(prefix="caihong-pose-tests-") as directory:
            run(Path(directory), compiler, args.sanitizers, args.fixture)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
