#!/usr/bin/env python3
"""Build/test a private daemon on native Fedora AArch64. Never install or restart."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PATCH = HERE / "patches/0001-reload-config-without-wall-clock-cache.patch"
REQUIRED_RED_FAILURES = {
    "future_directory_new_file", "existing_file_clock_rollback",
    "deleted_future_file", "same_time_same_size_replacement",
    "removed_last_key_defaults",
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def elf_aarch64(path):
    data = Path(path).read_bytes()[:64]
    return len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01" and int.from_bytes(data[18:20], "little") == 183


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Fedora 0.21.0-13 tree after all vendor patches")
    parser.add_argument("--fedora-spec", type=Path, required=True)
    parser.add_argument("--srpm", type=Path, required=True)
    parser.add_argument("--expected-srpm-sha256", required=True)
    parser.add_argument("--work-dir", type=Path, required=True, help="new directory, never the prepared source directory")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--build", action="store_true", help="run the native build; otherwise print a plan")
    args = parser.parse_args(argv)
    source = args.source.resolve(strict=True)
    spec = args.fedora_spec.resolve(strict=True)
    srpm = args.srpm.resolve(strict=True)
    if digest(srpm) != args.expected_srpm_sha256.lower():
        parser.error("source RPM SHA-256 differs from the operator-approved value")
    if args.jobs < 1 or args.jobs > 16:
        parser.error("jobs must be between 1 and 16")
    for rel in ("CMakeLists.txt", "src/common/ConfigReader.cpp", "src/common/ConfigReader.h"):
        if not (source / rel).is_file():
            parser.error("prepared source is missing " + rel)
    if "m_fileModificationTime" not in (source / "src/common/ConfigReader.cpp").read_text():
        parser.error("source is already patched or differs from the expected Fedora base")
    plan = {"source": str(source), "source_rpm": str(srpm), "source_rpm_sha256": digest(srpm),
            "fedora_spec": str(spec), "fedora_spec_sha256": digest(spec), "patch_sha256": digest(PATCH),
            "work_dir": str(args.work_dir.absolute()), "actions": ["verify source RPM signature/version",
                "copy complete prepared Fedora source", "compile/run real parser regression: red",
                "apply exact local patch", "compile/run real parser regression: green",
                "build only daemon target with native Qt6", "record evidence, no install/service action"]}
    print(json.dumps(plan, indent=2), flush=True)
    if not args.build:
        return 0
    if platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
        parser.error("build requires native Linux AArch64; cross-build and macOS execution are disabled")
    if args.work_dir.exists() or args.work_dir.is_symlink():
        parser.error("work-dir must not exist; preserve previous results")
    work = args.work_dir.resolve()
    if work == source or source in work.parents or work in source.parents:
        parser.error("source and work-dir must be separate trees")
    args.work_dir.mkdir(mode=0o700, parents=True)
    evidence = {"native_build": {"system": platform.system(), "machine": platform.machine().lower()},
                "inputs": plan, "commands": [], "success": False}
    evidence_path = work / "build-evidence.json"

    def run(command, cwd=None, check=True):
        result = subprocess.run([str(x) for x in command], cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        row = {"command": [str(x) for x in command], "cwd": str(cwd or Path.cwd()),
               "exit_code": result.returncode, "output": result.stdout}
        evidence["commands"].append(row)
        print(result.stdout, end="", flush=True)
        if check and result.returncode:
            raise RuntimeError("command failed: " + " ".join(row["command"]))
        return result

    try:
        signature = run(["rpmkeys", "--checksig", srpm])
        if "signatures OK" not in signature.stdout:
            raise RuntimeError("source RPM must have a trusted native RPM signature")
        nevra = run(["rpm", "-qp", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}", srpm]).stdout.strip()
        if nevra != "sddm-0.21.0-13.fc44.src":
            raise RuntimeError("unexpected source RPM: " + nevra)
        prepared = work / "source"
        shutil.copytree(source, prepared, symlinks=True)
        evidence["prepared_source_files"] = {
            str(p.relative_to(prepared)): digest(p) for p in sorted(prepared.rglob("*")) if p.is_file() and not p.is_symlink()
        }
        regression_build = work / "regression"
        run(["cmake", "-S", HERE / "tests", "-B", regression_build, "-DSDDM_SOURCE_DIR=" + str(prepared)])
        run(["cmake", "--build", regression_build, "--parallel", str(args.jobs)])
        red = run([regression_build / "config-reload-regression"], check=False)
        failures = {line.split()[1] for line in red.stdout.splitlines() if line.startswith("FAIL ")}
        if red.returncode == 0 or not REQUIRED_RED_FAILURES.issubset(failures) or "PASS unchanged_load" not in red.stdout:
            raise RuntimeError("unpatched real parser did not reproduce all required regressions")
        run(["patch", "--dry-run", "--fuzz=0", "-p1", "-i", PATCH], cwd=prepared)
        run(["patch", "--fuzz=0", "-p1", "-i", PATCH], cwd=prepared)
        run(["cmake", "--build", regression_build, "--parallel", str(args.jobs)])
        green = run([regression_build / "config-reload-regression"])
        if green.stdout.count("PASS ") != 8 or "FAIL " in green.stdout:
            raise RuntimeError("patched real parser did not pass exactly eight regression cases")
        daemon_build = work / "daemon"
        run(["cmake", "-S", prepared, "-B", daemon_build,
             "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=/usr",
             "-DCMAKE_INSTALL_SBINDIR=bin", "-DCMAKE_INSTALL_LIBDIR=lib64",
             "-DCMAKE_INSTALL_LIBEXECDIR=libexec", "-DBUILD_WITH_QT6=ON",
             "-DBUILD_MAN_PAGES=OFF", "-DENABLE_JOURNALD=ON",
             "-DSESSION_COMMAND=/etc/X11/xinit/Xsession", "-DWAYLAND_SESSION_COMMAND=/etc/sddm/wayland-session"])
        run(["cmake", "--build", daemon_build, "--target", "sddm", "--parallel", str(args.jobs)])
        binaries = [p for p in daemon_build.rglob("sddm") if p.is_file() and not p.is_symlink() and elf_aarch64(p)]
        if len(binaries) != 1:
            raise RuntimeError("expected one native AArch64 daemon; found " + str(binaries))
        daemon = binaries[0]
        linkage = run(["ldd", daemon])
        if "not found" in linkage.stdout:
            raise RuntimeError("native daemon has unresolved libraries")
        # SDDM 0.21.0 has no --version option; unknown arguments start a daemon.
        # --example-config exits before DaemonApp construction and has no seat action.
        run([daemon, "--example-config"])
        evidence["daemon"] = {"path": str(daemon), "sha256": digest(daemon), "bytes": daemon.stat().st_size}
        evidence["regression"] = {"red_failures": sorted(failures), "green_cases": 8,
                                  "source": "real Fedora ConfigReader.cpp; no parser copy or mocked algorithm"}
        evidence["success"] = True
    except BaseException as error:
        evidence["error"] = repr(error)
        raise
    finally:
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        evidence_path.chmod(0o600)
        print("Build evidence: " + str(evidence_path), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
