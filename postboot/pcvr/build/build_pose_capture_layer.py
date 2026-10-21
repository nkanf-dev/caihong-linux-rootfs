#!/usr/bin/env python3
"""Build the preserved 16-source ALVR capture layer in an external directory.

Requires Linux x86_64 C++17 tooling, libunwind development files and X11/Xrandr
headers. The compiler command may include an explicit FEX runner. No install or
runtime process is started. The custom negotiation shim uses --session-path.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import time

from provenance import (HERE, external_path, load_manifest, sha256,
                        verify_patch, verify_tree)


def prepare(work, headers, session_path, main_comm=False):
    source_manifest = load_manifest("source-manifest.json")
    header_manifest = load_manifest("vulkan-headers-manifest.json")
    verify_tree(HERE / "source", source_manifest["files"])
    verify_tree(headers, header_manifest["files"])
    pose_dir = HERE.parent / "patches/headpose"
    pose_manifest = json.loads((pose_dir / "manifest.json").read_text())
    patch = pose_dir / "alvr-v20.14.1-exact-compositor-pose.patch"
    verify_patch(patch, pose_manifest["patch_sha256"])
    if not PurePosixPath(session_path).is_absolute() or "\0" in session_path:
        raise ValueError("--session-path must be an absolute Linux session.json path")
    work = external_path(work)
    source = work / "source"
    output = work / "out"
    if source.exists() or output.exists():
        raise ValueError("Build work directory already contains source/ or out/; use a new directory")
    work.mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE / "source", source)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    if sha256((source / pose_manifest["path"]).read_bytes()) != pose_manifest["patched_sha256"]:
        raise ValueError("Staged head-pose source differs from the reviewed source")
    output.mkdir()
    shim = output / "ALVR_Negotiate.cpp"
    shim.write_text('#include "layer/layer.h"\n'
                    'extern "C" __attribute__((visibility("default"))) '
                    'VKAPI_ATTR VkResult VKAPI_CALL ALVR_Negotiate('
                    'VkNegotiateLayerInterface*nli){g_sessionPath=' +
                    json.dumps(session_path, ensure_ascii=True) +
                    ';return wsi_layer_Negotiate(nli); }\n')
    if main_comm:
        comm_dir = HERE.parent / "patches/main-comm"
        comm_manifest = json.loads((comm_dir / "manifest.json").read_text())
        for record in comm_manifest["files"]:
            verify_patch(comm_dir / record["path"], record["sha256"])
        template = (comm_dir / "ALVR_Negotiate.cpp.in").read_text()
        if template.count("@SESSION_PATH@") != 1:
            raise ValueError("Main-comm negotiation template must contain one session placeholder")
        escaped_session = json.dumps(session_path, ensure_ascii=True)[1:-1]
        shim.write_text(template.replace("@SESSION_PATH@", escaped_session))
        shutil.copyfile(comm_dir / "compositor_main_comm.h", output / "compositor_main_comm.h")
    exports = output / "layer.map"
    exports.write_text("{global: ALVR_Negotiate; local:*;};\n")
    layer = source / "alvr/vulkan_layer"
    server = source / "alvr/server_openvr/cpp"
    return source_manifest, layer, server, output, shim, exports


def commands(layer, server, output, shim, exports, headers, compiler, sources):
    common = ["-std=c++17", "-O2", "-fPIC", "-pthread", "-D_GNU_SOURCE",
              "-DVK_USE_PLATFORM_XLIB_XRANDR_EXT", "-Wno-unused-parameter",
              "-I" + str(layer), "-I" + str(server), "-I" + str(headers / "include")]
    objects = []
    result = []
    for index, source in enumerate([layer / path for path in sources] + [shim]):
        obj = output / (str(index) + "-" + source.stem + ".o")
        result.append(compiler + common + ["-c", str(source), "-o", str(obj)])
        objects.append(str(obj))
    library = output / "libalvr_vulkan_layer.so"
    result.append(compiler + ["-shared", "-pthread", "-Wl,--no-undefined",
                              "-Wl,--version-script=" + str(exports),
                              "-Wl,-soname,libalvr_vulkan_layer.so", "-o", str(library)] +
                  objects + ["-lunwind", "-ldl"])
    return result, library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--headers-dir", required=True, type=Path)
    parser.add_argument("--session-path", required=True, help="Explicit target Linux ALVR session.json path")
    parser.add_argument("--compiler-command", default="g++", help="Shell-quoted command, e.g. 'g++' or 'FEX /usr/bin/g++'")
    parser.add_argument("--dry-run", action="store_true", help="Verify inputs and stage source/shim, then print compile/link commands")
    parser.add_argument("--main-comm", action="store_true", help="Add the exact-build guarded compositor main-task-name constructor")
    args = parser.parse_args()
    compiler = shlex.split(args.compiler_command)
    if not compiler:
        parser.error("--compiler-command must not be empty")
    work = external_path(args.work_dir)
    headers = args.headers_dir.resolve()
    manifest, layer, server, output, shim, exports = prepare(work, headers, args.session_path, args.main_comm)
    steps, library = commands(layer, server, output, shim, exports,
                              headers, compiler, manifest["cpp_sources"])
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("FEX_") and key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
    temporary = work / "tmp"
    temporary.mkdir()
    environment["TMPDIR"] = str(temporary)
    start = time.monotonic()
    for index, command in enumerate(steps):
        print("LINK" if index == len(steps) - 1 else "COMPILE", shlex.join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, env=environment, check=True, timeout=180)
    result = {"scope": "16-source capture layer, exact head-pose patch and PR3357; custom explicit-path negotiation shim",
              "mode": "dry-run" if args.dry_run else "compiled", "compiler_command": compiler,
              "main_comm_repair": args.main_comm,
              "alvr_commit": manifest["commit"], "session_path": args.session_path,
              "elapsed_s": time.monotonic() - start, "output": str(library),
              "deployment": "not performed by this build script"}
    if not args.dry_run:
        result.update(bytes=library.stat().st_size, sha256=sha256(library.read_bytes()))
    (output / "build-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
