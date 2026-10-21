#!/usr/bin/env python3
"""Plan or repair the confirmed missing-iwd NetworkManager backend mismatch."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tempfile

CONFIG = Path("/etc/NetworkManager/conf.d/99-valve-wifi-backend.conf")
BACKUPS = Path("/var/lib/caihong/wifi-backend-backups")


class RepairError(RuntimeError):
    pass


def command(args, allow_failure=False):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode and not allow_failure:
        raise RepairError("{} failed: {}".format(args[0], result.stderr.strip()))
    return result.stdout


def unit_state(name, run=command):
    output = run(["systemctl", "show", name, "--no-pager",
                  "--property=LoadState,ActiveState,UnitFileState"], allow_failure=True)
    fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if not fields.get("LoadState") or not fields.get("ActiveState"):
        raise RepairError("Cannot read systemd state for " + name)
    return fields


def effective_backend(output):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(output)
        selected = parser.get("device", "wifi.backend", fallback=None)
    except configparser.Error as error:
        raise RepairError("Cannot parse effective NetworkManager config: " + str(error))
    # A matching device section could select another backend for this interface.
    for section in parser.sections():
        if section != "device" and parser.has_option(section, "wifi.backend"):
            raise RepairError("A device-specific Wi-Fi backend requires manual review")
    if selected not in ("iwd", "wpa_supplicant"):
        raise RepairError("No explicit supported effective Wi-Fi backend")
    return selected


def replace_backend(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepairError("Backend file is not UTF-8") from error
    section = None
    changes = 0
    output = []
    for line in text.splitlines(keepends=True):
        header = re.match(r"^\s*\[([^]]+)\]\s*(?:[#;].*)?$", line.rstrip("\r\n"))
        if header:
            section = header.group(1)
        if re.match(r"^\s*wifi\.backend\s*=", line):
            match = re.fullmatch(r"([ \t]*wifi\.backend[ \t]*=[ \t]*)iwd([ \t]*(?:\r?\n)?)", line)
            if section != "device" or not match:
                raise RepairError("Unexpected Wi-Fi backend assignment in Valve config")
            line = match.group(1) + "wpa_supplicant" + match.group(2)
            changes += 1
        output.append(line)
    if changes != 1:
        raise RepairError("Expected exactly one [device] wifi.backend=iwd assignment")
    return "".join(output).encode("utf-8")


def read_regular(path, require_root=True):
    # Refuse symlinked parent directories as well as a symlinked target.
    for item in (path,) + tuple(path.parents):
        if item.is_symlink():
            raise RepairError("Refusing symlink: " + str(item))
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RepairError("Backend config must be a regular file with one link")
        if require_root and info.st_uid != 0:
            raise RepairError("Backend config must be owned by root")
        if info.st_mode & 0o022:
            raise RepairError("Backend config must not be group/world writable")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RepairError("Backend config exceeds 1 MiB")
        return data, info
    finally:
        os.close(descriptor)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def atomic_replace(path, data, info):
    descriptor, temporary = tempfile.mkstemp(prefix=".wifi-backend-", dir=str(path.parent))
    try:
        os.fchmod(descriptor, stat.S_IMODE(info.st_mode))
        if os.geteuid() == 0:
            os.fchown(descriptor, info.st_uid, info.st_gid)
        # Preserve Fedora's SELinux label and any other existing xattrs.
        if hasattr(os, "listxattr"):
            for name in os.listxattr(str(path), follow_symlinks=False):
                os.setxattr(descriptor, name, os.getxattr(str(path), name, follow_symlinks=False))
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_backup(directory, data):
    for item in (directory,) + tuple(directory.parents):
        if item.is_symlink():
            raise RepairError("Refusing symlinked backup path: " + str(item))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RepairError("Backup directory must be owned by this operator with mode 0700")
    descriptor, path = tempfile.mkstemp(prefix="99-valve-", suffix=".conf", dir=str(directory))
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def inspect_state(config=CONFIG, run=command, exists=None, require_root=True):
    exists = exists or (lambda path: Path(path).exists())
    data, info = read_regular(config, require_root)
    selected = effective_backend(run(["NetworkManager", "--print-config"]))
    iwd = unit_state("iwd.service", run)
    wpa = unit_state("wpa_supplicant.service", run)
    nm = unit_state("NetworkManager.service", run)
    result = {"config": str(config), "effective_backend": selected,
              "iwd": iwd, "wpa_supplicant": wpa, "NetworkManager": nm,
              "sha256_before": hashlib.sha256(data).hexdigest()}
    if selected == "wpa_supplicant":
        result.update(action="none", reason="wpa_supplicant is already selected")
        return result, data, info, None
    iwd_paths = ("/usr/lib/iwd/iwd", "/usr/libexec/iwd", "/usr/sbin/iwd", "/usr/bin/iwd",
                 "/usr/share/dbus-1/system-services/net.connman.iwd.service")
    if iwd["LoadState"] != "not-found" or any(exists(path) for path in iwd_paths):
        raise RepairError("iwd is present; this tool does not change an installed backend")
    if wpa["LoadState"] != "loaded" or wpa.get("UnitFileState") == "masked":
        raise RepairError("wpa_supplicant.service is unavailable or masked")
    if not any(exists(path) for path in ("/usr/sbin/wpa_supplicant", "/usr/bin/wpa_supplicant")):
        raise RepairError("wpa_supplicant binary is unavailable")
    if not exists("/usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service"):
        raise RepairError("wpa_supplicant D-Bus activation file is unavailable")
    if nm["LoadState"] != "loaded" or nm["ActiveState"] not in ("active", "inactive", "failed"):
        raise RepairError("NetworkManager must be loaded and not in a transition")
    updated = replace_backend(data)
    result.update(action="restart" if nm["ActiveState"] == "active" else "start",
                  reason="iwd selected but absent; installed wpa_supplicant can replace it",
                  sha256_after=hashlib.sha256(updated).hexdigest())
    return result, data, info, updated


def require_apply_environment():
    if platform.system() != "Linux" or os.geteuid() != 0:
        raise RepairError("--apply requires native Linux root")


def repair(apply=False, config=CONFIG, backups=BACKUPS, run=command, exists=None,
           require_root=True):
    if apply:
        require_apply_environment()
    result, original, info, updated = inspect_state(config, run, exists, require_root)
    result["applied"] = False
    if not apply or updated is None:
        return result
    # Recheck probes and exact inode/content immediately before mutation.
    again, current, current_info, repeated = inspect_state(config, run, exists, require_root)
    if (current != original or fingerprint(current_info) != fingerprint(info)
            or repeated != updated or again["action"] != result["action"]):
        raise RepairError("Backend state changed during review; no file was changed")
    final_data, final_info = read_regular(config, require_root)
    if final_data != original or fingerprint(final_info) != fingerprint(info):
        raise RepairError("Backend state changed during review; no file was changed")
    result["backup"] = private_backup(backups, original)
    # Backing up can take time. Preserve another writer's newer file instead of
    # replacing it. This is a bounded recheck, not a lock shared with root writers.
    before_replace, before_replace_info = read_regular(config, require_root)
    if before_replace != original or fingerprint(before_replace_info) != fingerprint(info):
        raise RepairError("Backend state changed after backup; no file was changed")
    atomic_replace(config, updated, info)
    try:
        if effective_backend(run(["NetworkManager", "--print-config"])) != "wpa_supplicant":
            raise RepairError("Another config still overrides the backend")
    except Exception:
        # No service operation happened. Undo only our own unchanged replacement.
        actual, replacement_info = read_regular(config, require_root)
        if actual != updated:
            raise RepairError("Config changed after replacement; restore from private backup manually")
        atomic_replace(config, original, replacement_info)
        raise
    # Exactly one service operation. Never call RootManager.SetWifiBackend here.
    run(["systemctl", result["action"], "NetworkManager.service"])
    result["applied"] = True
    result["NetworkManager_after"] = unit_state("NetworkManager.service", run)
    if result["NetworkManager_after"]["ActiveState"] != "active":
        raise RepairError("Backend corrected, but NetworkManager is not active; inspect the journal")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the guarded repair (Linux root only)")
    args = parser.parse_args()
    try:
        print(json.dumps(repair(apply=args.apply), indent=2, sort_keys=True))
    except (RepairError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
