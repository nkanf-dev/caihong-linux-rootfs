#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install files only. Never start/restart Steam or Decky, select a slot, or reboot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

NAME = "CaihongPowerMenu"
REQUIRED_UID = 0
ROOT = Path(__file__).resolve().parent
CONFIG = Path("/etc/caihong-power-menu.json")
SLOT = Path("/usr/local/sbin/caihong-slot")
QBOOT = Path("/usr/local/sbin/qbootctl")
EXPECTED_SLOT_SHA256 = "a03bc5f6a136485b5aa7401f6523d57467bb4598f0f6777ac7b45159c4e96907"
PAYLOAD = ("main.py", "plugin.json", "package.json", "dist/index.js", "LICENSE", "source-references.json", "frontend-references.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_path(path, directory=False):
    """Allow the Steam-owned homebrew parent, but reject writable/symlink target files."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"Expected root-owned, non-writable path: {path}")
    if (directory and not stat.S_ISDIR(info.st_mode)) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError(f"Unexpected file type: {path}")


def target_path(homebrew):
    if not homebrew.is_absolute() or homebrew.resolve() != homebrew:
        raise ValueError("--homebrew must be an absolute path without symlinks")
    plugins = homebrew / "plugins"
    if not plugins.is_dir() or plugins.is_symlink():
        raise ValueError("Existing Decky plugins directory required")
    return plugins / NAME


def open_dir(path):
    """Pin each directory with O_NOFOLLOW. Parent renames cannot redirect later writes."""
    if not path.is_absolute():
        raise ValueError("Absolute directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def validate_dirfd(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != REQUIRED_UID or info.st_mode & 0o022:
        raise ValueError("Plugins directory must be root-owned and not group/other writable")


def checked_dir(name, parent_fd):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        validate_dirfd(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_at(name, fd):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        info = os.fstat(f)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != REQUIRED_UID or info.st_mode & 0o022 or info.st_size > 4 * 1024 * 1024:
            raise ValueError("Untrusted plugin file")
        with os.fdopen(f, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(f)


def write_at(name, fd, data):
    f = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
    with os.fdopen(f, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def exists_at(name, fd):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def install(homebrew, qbootctl_sha256, approve, loader_version):
    if loader_version != "3.3.0":
        raise ValueError("This package is pinned to Decky Loader 3.3.0")
    if not approve:
        raise ValueError("Explicit Android A / Linux B deployment approval required")
    if len(qbootctl_sha256) != 64 or any(c not in "0123456789abcdef" for c in qbootctl_sha256):
        raise ValueError("A verified qbootctl SHA256 is required")
    for path in [SLOT, QBOOT]:
        for parent in [path, *path.parents]:
            root_path(parent, parent != path)
        if not os.access(path, os.X_OK):
            raise ValueError(f"Missing executable {path}")
    if digest(SLOT) != EXPECTED_SLOT_SHA256 or digest(QBOOT) != qbootctl_sha256:
        raise ValueError("Installed boot tool does not match the approved SHA256")
    target = target_path(homebrew)
    payload = {}
    for rel in PAYLOAD:
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing build payload {rel}; run npm ci && npm run build")
        payload[rel] = path.read_bytes()
    cfg = {"schema": 1, "approved": True, "android_slot": "a", "linux_slot": "b",
           "slot_script_sha256": EXPECTED_SLOT_SHA256, "qbootctl_sha256": qbootctl_sha256}
    cfg_bytes = (json.dumps(cfg, indent=2) + "\n").encode()
    receipt = {"schema": 1, "name": NAME,
               "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in payload.items()},
               "config_sha256": hashlib.sha256(cfg_bytes).hexdigest()}
    plugins_fd, etc_fd = open_dir(target.parent), open_dir(CONFIG.parent)
    try:
        validate_dirfd(plugins_fd)
    except BaseException:
        os.close(plugins_fd)
        os.close(etc_fd)
        raise
    stage = ".caihong-power-stage-" + os.urandom(16).hex()
    stage_fd = dist_fd = None
    created_config = committed = False
    try:
        if exists_at(NAME, plugins_fd) or exists_at(CONFIG.name, etc_fd):
            raise ValueError("Existing plugin/config found; remove this package explicitly before reinstalling")
        os.mkdir(stage, mode=0o755, dir_fd=plugins_fd)
        stage_fd = checked_dir(stage, plugins_fd)
        os.mkdir("dist", mode=0o755, dir_fd=stage_fd)
        dist_fd = checked_dir("dist", stage_fd)
        for rel, data in payload.items():
            write_at(Path(rel).name, dist_fd if rel.startswith("dist/") else stage_fd, data)
        write_at("install-receipt.json", stage_fd, (json.dumps(receipt, indent=2) + "\n").encode())
        # O_EXCL refuses existing config. This is a file install, not a slot operation.
        f = os.open(CONFIG.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=etc_fd)
        created_config = True
        with os.fdopen(f, "wb") as stream:
            stream.write(cfg_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if exists_at(NAME, plugins_fd):
            raise ValueError("Plugin appeared during installation")
        info = os.stat(stage, dir_fd=plugins_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (os.fstat(stage_fd).st_dev, os.fstat(stage_fd).st_ino):
            raise ValueError("Staging directory changed")
        os.rename(stage, NAME, src_dir_fd=plugins_fd, dst_dir_fd=plugins_fd)
        committed = True
    finally:
        if not committed:
            if created_config:
                os.unlink(CONFIG.name, dir_fd=etc_fd)
            if dist_fd is not None:
                for name in os.listdir(dist_fd):
                    os.unlink(name, dir_fd=dist_fd)
            if stage_fd is not None:
                for name in os.listdir(stage_fd):
                    if name != "dist":
                        os.unlink(name, dir_fd=stage_fd)
                os.rmdir("dist", dir_fd=stage_fd)
                # Remove the stage name only if it still identifies the opened directory.
                if exists_at(stage, plugins_fd) and os.stat(stage, dir_fd=plugins_fd, follow_symlinks=False).st_ino == os.fstat(stage_fd).st_ino:
                    os.rmdir(stage, dir_fd=plugins_fd)
        for fd in [dist_fd, stage_fd, plugins_fd, etc_fd]:
            if fd is not None:
                os.close(fd)
    return {"installed": str(target), "config": str(CONFIG), "activation": "next normal Decky/Steam startup"}


def remove(homebrew):
    target = target_path(homebrew)
    plugins_fd, etc_fd = open_dir(target.parent), open_dir(CONFIG.parent)
    try:
        validate_dirfd(plugins_fd)
    except BaseException:
        os.close(plugins_fd)
        os.close(etc_fd)
        raise
    target_fd = dist_fd = None
    try:
        target_fd = checked_dir(NAME, plugins_fd)
        dist_fd = checked_dir("dist", target_fd)
        receipt = json.loads(read_at("install-receipt.json", target_fd))
        if receipt.get("schema") != 1 or receipt.get("name") != NAME or set(receipt.get("files", {})) != set(PAYLOAD):
            raise ValueError("Unrecognized install receipt")
        expected = {Path(rel).name for rel in PAYLOAD if not rel.startswith("dist/")} | {"dist", "install-receipt.json"}
        if set(os.listdir(target_fd)) != expected or set(os.listdir(dist_fd)) != {"index.js"}:
            raise ValueError("Plugin has extra or missing files; preserve and inspect it before removal")
        for rel, sha in receipt["files"].items():
            data = read_at(Path(rel).name, dist_fd if rel.startswith("dist/") else target_fd)
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError(f"Changed plugin file preserved: {rel}")
        if hashlib.sha256(read_at(CONFIG.name, etc_fd)).hexdigest() != receipt["config_sha256"]:
            raise ValueError("Changed deployment config preserved")
        # The owning Decky session must already be stopped normally by the user.
        os.unlink("index.js", dir_fd=dist_fd)
        os.rmdir("dist", dir_fd=target_fd)
        for name in expected - {"dist"}:
            os.unlink(name, dir_fd=target_fd)
        info = os.stat(NAME, dir_fd=plugins_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (os.fstat(target_fd).st_dev, os.fstat(target_fd).st_ino):
            raise ValueError("Plugin directory moved; configuration preserved")
        os.rmdir(NAME, dir_fd=plugins_fd)
        os.unlink(CONFIG.name, dir_fd=etc_fd)
    finally:
        for fd in [dist_fd, target_fd, plugins_fd, etc_fd]:
            if fd is not None:
                os.close(fd)
    return {"removed": str(target), "steam_or_decky_restarted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "install", "remove"))
    parser.add_argument("--homebrew", type=Path, required=True)
    parser.add_argument("--loader-version", default="3.3.0")
    parser.add_argument("--qbootctl-sha256", default="")
    parser.add_argument("--approve-android-a-linux-b", action="store_true")
    args = parser.parse_args()
    if args.action == "plan":
        result = {"plugin": str(target_path(args.homebrew)), "config": str(CONFIG),
                  "writes": False, "commands": [], "loader_version": "3.3.0", "slot_script_sha256": EXPECTED_SLOT_SHA256}
    else:
        if sys.platform != "linux" or os.geteuid() != 0:
            parser.error("Install/remove must run as root on the Linux target")
        result = install(args.homebrew, args.qbootctl_sha256, args.approve_android_a_linux_b, args.loader_version) if args.action == "install" else remove(args.homebrew)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
