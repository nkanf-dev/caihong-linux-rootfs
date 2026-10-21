#!/usr/bin/env python3
"""Build the pinned Steam-mode FEX into /work/stage. Never deploy it."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PIN = "938eedfcd79eb00e86561fbdf4933770766f0ba9"
TAG = "eac-2610.3"
REPO = "https://github.com/StonkGuy/FEX.git"
WORK = Path("/work")
SRC = WORK / "FEX"
BUILD = WORK / "build-steam"
STAGE = WORK / "stage"
SUBMODULES = {
    "Source/Common/cpp-optparse": "9f94388a339fcbb0bc95c17768eb786c85988f6e",
    "External/fmt": "c07e2aa4b130b4fd359a1c6455a5201b17af01fa",
    "External/drm-headers": "3e49836995c1dcb3df709440ad2f270b569c6a5f",
    "External/xxhash": "e626a72bc2321cd320e953a0ccf1584cad60f363",
    "External/jemalloc_glibc": "8436195ad5e1bc347d9b39743af3d29abee59f06",
    "External/range-v3": "ca1388fb9da8e69314dda222dc7b139ca84e092f",
    "External/unordered_dense": "3234af2c03549bc85656bfd3a86993bf1cd8aef1",
    "External/rpmalloc": "09142d726429416bfa7b459151515fe3ab7622dd",
}
TARGETS = ["FEX", "FEXBash", "FEXGetConfig", "FEXOfflineCompiler", "FEXServer",
           "FEXServerManager", "FEXpidof", "FEXCompatTool"]
OPTIONS = [
    "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=clang", "-DCMAKE_CXX_COMPILER=clang++",
    "-DBUILD_STEAM_SUPPORT=ON", "-DBUILD_TESTING=OFF", "-DBUILD_THUNKS=OFF",
    "-DBUILD_FEXCONFIG=OFF", "-DENABLE_LTO=OFF", "-DENABLE_ASSERTIONS=OFF",
    "-DTUNE_CPU=native", "-DCMAKE_CXX_SCAN_FOR_MODULES=OFF", "-DCMAKE_INSTALL_PREFIX=/usr",
]

def run(args, cwd=WORK, env=None):
    print("+ " + " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout

def command(args, cwd=WORK, env=None):
    print("+ " + " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)

def save(name, data):
    (WORK / "logs" / name).write_text(data)

def main():
    if os.uname().machine != "aarch64" or os.sysconf("SC_PAGE_SIZE") != 4096:
        raise RuntimeError("Run natively on the target aarch64 Linux device with 4 KiB pages")
    if os.getuid() == 0:
        raise RuntimeError("Container must run as the non-root keep-id user")
    if shutil.disk_usage(WORK).free < 20 * 1024**3:
        raise RuntimeError("Need at least 20 GiB free before starting this phase")
    (WORK / "logs").mkdir(exist_ok=True)
    save("container-os-release.txt", Path("/etc/os-release").read_text())
    save("container-rpms.txt", run(["rpm", "-qa", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n"]))
    for cmd in (["clang", "--version"], ["cmake", "--version"], ["ninja", "--version"],
                ["ld.lld", "--version"], ["getconf", "GNU_LIBC_VERSION"]):
        print(run(cmd), flush=True)
    if not SRC.exists():
        command(["git", "clone", "--depth", "1", "--branch", TAG, REPO, SRC])
    if not (SRC / ".git").is_dir():
        raise RuntimeError("Existing source is not a git checkout; leave it intact and inspect it")
    for ref in ("HEAD", TAG + "^{commit}"):
        got = run(["git", "rev-parse", ref], SRC).strip()
        if got != PIN:
            raise RuntimeError(f"Source pin mismatch: {ref} = {got}, expected {PIN}")
    if run(["git", "status", "--porcelain", "--untracked-files=all"], SRC).strip():
        raise RuntimeError("Source tree has changes; no reset or cleanup is performed")
    command(["git", "submodule", "update", "--init", "--recursive", "--depth", "1",
             "--jobs", "2", "--", *SUBMODULES], SRC)
    for path, expected in SUBMODULES.items():
        actual = run(["git", "rev-parse", "HEAD"], SRC / path).strip()
        if actual != expected:
            raise RuntimeError(f"Submodule mismatch: {path}: {actual}")
        if run(["git", "status", "--porcelain", "--untracked-files=all"], SRC / path).strip():
            raise RuntimeError(f"Dirty submodule: {path}")
    save("source-lock.json", json.dumps({"repo": REPO, "tag": TAG, "commit": PIN,
                                        "submodules": SUBMODULES}, indent=2) + "\n")
    save("submodules.txt", run(["git", "submodule", "status", "--recursive"], SRC))
    command(["cmake", "-S", SRC, "-B", BUILD, "-G", "Ninja", *OPTIONS])
    cache = (BUILD / "CMakeCache.txt").read_text()
    for item in OPTIONS:
        key, value = item[2:].split("=", 1)
        # The cache preserves Release spelling; verify the configuration is not silently ignored.
        entries = [line.split("=", 1)[-1] for line in cache.splitlines() if line.startswith(key + ":")]
        matches = any(Path(entry).name == value if key in ["CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER"]
                      else entry == value for entry in entries)
        if not matches:
            raise RuntimeError(f"CMake cache did not preserve {item}")
    if "ENABLE_STEAM_SUPPORT:" in cache:
        raise RuntimeError("Unknown ENABLE_STEAM_SUPPORT variable found; use BUILD_STEAM_SUPPORT")
    save("CMakeCache.txt", cache)
    command(["cmake", "--build", BUILD, "--target", *TARGETS, "-j2"])
    if STAGE.exists() and any(STAGE.iterdir()):
        raise RuntimeError("stage is not empty; preserve it or rename it before a new staging operation")
    STAGE.mkdir(exist_ok=True)
    env = dict(os.environ, DESTDIR=str(STAGE))
    command(["cmake", "--install", BUILD, "--component", "Runtime", "--strip"], env=env)
    required = [STAGE / "usr/bin" / t for t in TARGETS if t != "FEXCompatTool"]
    required += [STAGE / f for f in ["FEXCompatTool", "VERSIONS.txt", "ConfigTemplate.json",
                                    "emulator.json", "toolmanifest.vdf"]]
    for p in required:
        if not p.is_file() or p.stat().st_size == 0:
            raise RuntimeError(f"Incomplete stage: {p}")
    artifacts = {}
    for p in sorted(STAGE.rglob("*")):
        if p.is_file():
            artifacts[str(p.relative_to(STAGE))] = {"bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    save("stage-manifest.json", json.dumps(artifacts, indent=2) + "\n")
    versions = [run(["readelf", "--version-info", p]) for p in required
                if p.name not in ["VERSIONS.txt", "ConfigTemplate.json", "emulator.json", "toolmanifest.vdf"]]
    save("stage-symbol-versions.txt", "\n".join(versions))
    save("build-complete.json", json.dumps({"commit": PIN, "tag": TAG,
         "finished_unix": time.time(), "stage": str(STAGE), "validated": False,
         "deployment": "not performed"}, indent=2) + "\n")
    print("BUILD COMPLETE: /work/stage. No install, Steam write, game, or EAC launch was performed.", flush=True)

if __name__ == "__main__":
    main()
