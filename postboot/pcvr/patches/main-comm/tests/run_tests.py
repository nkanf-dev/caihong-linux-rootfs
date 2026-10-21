#!/usr/bin/env python3
"""Run source-only compositor comm tests with mocked process/module APIs."""
import argparse
from pathlib import Path
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REPOSITORY = next((parent for parent in HERE.parents if (parent / ".git").exists()), HERE.parent)


def run(directory, compiler, sanitizers):
    directory = directory.resolve()
    if directory == REPOSITORY or REPOSITORY in directory.parents:
        raise ValueError("Test output must be outside the repository")
    directory.mkdir(parents=True, exist_ok=True)
    flags = ["-std=c++17", "-Wall", "-Wextra", "-I" + str(HERE / "include")]
    flags += (["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
              if sanitizers else ["-O2"])
    for name in ["test_comm", "test_constructor"]:
        binary = directory / name
        command = compiler + flags + [str(HERE / (name + ".cpp")), "-o", str(binary)]
        print("COMPILE", shlex.join(command), flush=True)
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compiler-command", default="clang++")
    parser.add_argument("--sanitizers", action="store_true")
    args = parser.parse_args()
    compiler = shlex.split(args.compiler_command)
    if not compiler:
        parser.error("Compiler command must not be empty")
    if args.output_dir:
        run(args.output_dir, compiler, args.sanitizers)
    else:
        with tempfile.TemporaryDirectory(prefix="caihong-main-comm-tests-") as directory:
            run(Path(directory), compiler, args.sanitizers)


if __name__ == "__main__":
    main()
