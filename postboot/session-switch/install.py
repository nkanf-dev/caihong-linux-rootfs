#!/usr/bin/env python3
"""Stage a locally built SDDM daemon. Plans are read-only; no service is managed.

The root argument on Installer is for isolated tests only. The CLI always uses /.
"""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import struct
import subprocess
import sys
import tempfile
import uuid


DROPIN = "/etc/systemd/system/sddm.service.d/90-caihong-config-reload.conf"
PRIVATE = "/usr/local/libexec/caihong-sddm"
STATE = "/var/lib/caihong-sddm"
VENDOR = "/usr/lib/systemd/system/sddm.service"
MAX_BINARY = 128 * 1024 * 1024
MAX_RECORD = 2 * 1024 * 1024


class InstallError(RuntimeError):
    pass


def native_preflight():
    if platform.system() != "Linux" or platform.machine().lower() != "aarch64":
        raise InstallError("--apply requires native Linux aarch64")
    if os.geteuid() != 0:
        raise InstallError("--apply requires root")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, limit):
    """Read one opened, nonsymlink regular file, with a bounded allocation."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise InstallError(f"not a bounded regular file: {path}")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) > limit or (before.st_dev, before.st_ino, before.st_size,
                            before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns):
        raise InstallError(f"file changed while reading: {path}")
    return data, after


def candidate(source, expected, evidence_path):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise InstallError("--expected-sha256 must contain 64 hexadecimal digits")
    expected = expected.lower()
    source = Path(os.path.abspath(source))
    data, info = read_regular(source, MAX_BINARY)
    if digest(data) != expected:
        raise InstallError("candidate SHA256 does not match --expected-sha256")
    # ELF64, little endian, current version, ET_EXEC/ET_DYN, EM_AARCH64.
    if (len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<HH", data, 16) not in ((2, 183), (3, 183))):
        raise InstallError("candidate must be an ELF64 AArch64 executable")
    evidence_path = Path(os.path.abspath(evidence_path))
    raw, _ = read_regular(evidence_path, MAX_RECORD // 2)
    try:
        evidence = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise InstallError("build evidence must be JSON") from error
    if not isinstance(evidence, dict):
        raise InstallError("build evidence must be a JSON object")
    if (evidence.get("native_build") != {"system": "Linux", "machine": "aarch64"}
            and not (isinstance(evidence.get("native_build"), dict)
                     and evidence["native_build"].get("system") == "Linux"
                     and evidence["native_build"].get("machine") == "aarch64")):
        raise InstallError("build evidence must record native Linux aarch64")
    if evidence.get("success") is not True:
        raise InstallError("build evidence must record success=true")
    if "regression" in evidence and (
            not isinstance(evidence["regression"], dict)
            or type(evidence["regression"].get("green_cases")) is not int
            or evidence["regression"]["green_cases"] != 8):
        raise InstallError("regression summary, when present, must record eight green cases")
    if not isinstance(evidence.get("daemon"), dict) or evidence["daemon"].get("sha256") != expected:
        raise InstallError("build evidence daemon.sha256 does not match the candidate")
    details = {
        "source": str(source), "sha256": expected, "elf_machine": "AArch64",
        "size": len(data), "uid": info.st_uid, "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode), "mtime_ns": info.st_mtime_ns,
        "regression_summary": evidence.get("regression", "omitted from supplied evidence"),
        "build_evidence": {"source": str(evidence_path), "sha256": digest(raw),
                           "bytes_base64": base64.b64encode(raw).decode("ascii")},
    }
    return data, details


class Installer:
    def __init__(self, root=Path("/"), owner=0, group=0, runner=subprocess.run):
        # No CLI option exposes these filesystem/ownership test seams.
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.resolve() != self.root:
            raise InstallError("test root must be absolute and contain no symlinks")
        self.owner, self.group, self.runner = owner, group, runner
        self._check_dir(self.root)

    def path(self, logical):
        logical = Path(logical)
        if not logical.is_absolute() or ".." in logical.parts:
            raise InstallError("target path escapes the root")
        return self.root.joinpath(*logical.parts[1:])

    def _check_dir(self, path, private=False):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner
                or stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022)):
            raise InstallError(f"untrusted directory: {path}")

    def directory(self, logical, create=False, private=False):
        path = self.path(logical)
        current = self.root
        self._check_dir(current)
        for part in path.relative_to(self.root).parts:
            current = current / part
            if not current.exists() and not current.is_symlink():
                if not create:
                    return path
                current_logical = "/" + str(current.relative_to(self.root))
                owned_private = any(current_logical == base or current_logical.startswith(base + "/")
                                    for base in (STATE, PRIVATE))
                current.mkdir(mode=0o700 if owned_private else 0o755)
                os.chown(current, self.owner, self.group)
                self.sync(current.parent)
            self._check_dir(current)
        if current.exists() and private:
            self._check_dir(current, private=True)
        return path

    def trusted(self, logical, missing=False, private=False):
        path = self.path(logical)
        self.directory(str(Path(logical).parent))
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing:
                return None
            raise
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o022
                or (private and stat.S_IMODE(info.st_mode) & 0o077)):
            raise InstallError(f"untrusted file: {path}")
        binary = logical == "/usr/bin/sddm" or re.fullmatch(re.escape(PRIVATE) + r"/[0-9a-f]{64}/sddm", logical)
        limit = MAX_BINARY if binary else MAX_RECORD
        data, opened = read_regular(path, limit)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise InstallError(f"file changed before reading: {path}")
        return data, opened

    @staticmethod
    def sync(directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def atomic(self, logical, data, mode, uid=None, gid=None, label=None, prepare=None):
        parent = self.directory(str(Path(logical).parent))
        if not parent.exists():
            raise InstallError(f"missing target directory: {parent}")
        self.trusted(logical, missing=True)
        fd, temporary = tempfile.mkstemp(prefix=".caihong-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchown(stream.fileno(), self.owner if uid is None else uid,
                          self.group if gid is None else gid)
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                if label is not None:
                    os.setxattr(stream.fileno(), "security.selinux", base64.b64decode(label, validate=True))
                if prepare is not None:
                    prepare(Path(temporary))
                os.fsync(stream.fileno())
            self.trusted(logical, missing=True)
            os.replace(temporary, self.path(logical))
            self.sync(parent)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)

    def unit_command(self, executable):
        # Refuse full-unit overrides instead of guessing an effective unit.
        for prefix in ("/etc", "/run", "/usr/local/lib"):
            if self.trusted(f"{prefix}/systemd/system/sddm.service", missing=True):
                raise InstallError("local sddm.service override requires manual review")
        vendor, _ = self.trusted(VENDOR)
        text = vendor.decode("utf-8")
        section, commands = "", []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                section = stripped
            elif section == "[Service]" and re.match(r"\s*ExecStart\s*=", line):
                commands.append(line)
        if len(commands) != 1 or commands[0].rstrip().endswith("\\"):
            raise InstallError("vendor unit must have one simple ExecStart")
        match = re.fullmatch(r"\s*ExecStart\s*=\s*/usr/bin/sddm(?P<args>(?:[ \t].*)?)", commands[0])
        if not match:
            raise InstallError("vendor ExecStart must run /usr/bin/sddm")
        for prefix in ("/etc", "/run", "/usr/local/lib", "/usr/lib"):
            for name in ("sddm.service.d", "display-manager.service.d", "service.d"):
                logical = f"{prefix}/systemd/system/{name}"
                directory = self.directory(logical)
                if directory.exists():
                    for entry in sorted(directory.glob("*.conf")):
                        entry_logical = "/" + str(entry.relative_to(self.root))
                        if entry_logical == DROPIN:
                            continue
                        data, _ = self.trusted(entry_logical)
                        if re.search(rb"(?m)^\s*ExecStart\s*=", data):
                            raise InstallError(f"other ExecStart drop-in requires review: {entry_logical}")
        return "[Service]\nExecStart=\nExecStart=" + executable + match["args"] + "\n"

    def selinux_enabled(self):
        return self.path("/sys/fs/selinux/enforce").exists()

    def tool(self, logical):
        # Packaged restorecon can be a symlink to setfiles. Only tool lookup may
        # resolve symlinks; installation and receipt paths never do.
        resolved = self.path(logical).resolve(strict=True)
        try:
            relative = resolved.relative_to(self.root / "usr")
        except ValueError as error:
            raise InstallError("SELinux helper escapes trusted /usr") from error
        self.trusted("/usr/" + str(relative))
        # Keep argv[0] as restorecon: its packaged symlink can target setfiles,
        # which selects its operation from the invoked basename.
        current = self.root
        for part in self.path(logical).relative_to(self.root).parts:
            current = current / part
            info = current.lstat()
            if info.st_uid != self.owner:
                raise InstallError("untrusted SELinux helper link")
            if not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022:
                raise InstallError("writable SELinux helper path")
        return self.path(logical)

    def command(self, tool, *args):
        self.runner([str(self.tool(tool)), *map(str, args)], check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def previous(self, labels):
        existing = self.trusted(DROPIN, missing=True)
        if existing is None:
            return {"exists": False}, None
        data, info = existing
        previous = {"exists": True, "sha256": digest(data),
                    "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}
        if labels:
            previous["selinux_base64"] = base64.b64encode(
                os.getxattr(self.path(DROPIN), "security.selinux")).decode("ascii")
        return previous, data

    def plan(self, source, expected, evidence):
        data, details = candidate(source, expected, evidence)
        executable = f"{PRIVATE}/{details['sha256']}/sddm"
        dropin = self.unit_command(executable)
        self.previous(False)
        return data, {"action": "plan-install", "candidate": details,
                      "private_executable": executable, "dropin": DROPIN,
                      "dropin_text": dropin, "receipts": f"{STATE}/receipts",
                      "service_action": "none; running SDDM is unchanged"}

    @contextmanager
    def locked(self):
        directory = self.directory(STATE, create=True, private=True)
        logical = f"{STATE}/lock"
        self.trusted(logical, missing=True, private=True)
        fd = os.open(directory / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise InstallError("untrusted lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise InstallError("another installer is active") from error
            yield
        finally:
            os.close(fd)

    def save_receipt(self, logical, record):
        self.atomic(logical, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(), 0o600)

    def restore(self, record, backup):
        previous = record["previous"]
        if previous["exists"]:
            saved, _ = self.trusted(backup, private=True)
            if digest(saved) != previous["sha256"]:
                raise InstallError("backup SHA256 mismatch")
            self.atomic(DROPIN, saved, previous["mode"], previous["uid"], previous["gid"],
                        label=previous.get("selinux_base64"))
        elif self.trusted(DROPIN, missing=True) is not None:
            self.path(DROPIN).unlink()
            self.sync(self.path(DROPIN).parent)

    def apply(self, source, expected, evidence):
        native_preflight()
        # Validate inputs and all existing targets before making directories.
        data, plan = self.plan(source, expected, evidence)
        labels = self.selinux_enabled()
        if labels:
            self.trusted("/usr/bin/sddm")
            self.tool("/usr/bin/chcon")
            self.tool("/usr/sbin/restorecon")
        with self.locked():
            # Recheck vendor/drop-ins after obtaining the installer lock.
            if self.unit_command(plan["private_executable"]) != plan["dropin_text"]:
                raise InstallError("unit changed while preparing the installation")
            previous, old_bytes = self.previous(labels)
            transaction = uuid.uuid4().hex
            transaction_dir = f"{STATE}/receipts/{transaction}"
            self.directory(transaction_dir, create=True, private=True)
            receipt = f"{transaction_dir}/receipt.json"
            backup = f"{transaction_dir}/previous-dropin"
            if old_bytes is not None:
                self.atomic(backup, old_bytes, 0o600)
            record = {"version": 1, "transaction": transaction, "status": "prepared",
                      "candidate": plan["candidate"], "private_executable": plan["private_executable"],
                      "dropin": DROPIN, "dropin_text": plan["dropin_text"],
                      "previous": previous, "service_action": plan["service_action"]}
            self.save_receipt(receipt, record)
            changed = False
            try:
                self.directory(f"{PRIVATE}/{plan['candidate']['sha256']}", create=True, private=True)
                existing = self.trusted(plan["private_executable"], missing=True)
                if existing and digest(existing[0]) != plan["candidate"]["sha256"]:
                    raise InstallError("existing private executable has unexpected content")
                label_candidate = None
                if labels:
                    label_candidate = lambda temporary: self.command(
                        "/usr/bin/chcon", "--reference=" + str(self.path("/usr/bin/sddm")), "--", temporary)
                self.atomic(plan["private_executable"], data, 0o755, prepare=label_candidate)
                self.directory(str(Path(DROPIN).parent), create=True)
                # From here even an fsync/label error requires exact restoration.
                changed = True
                self.atomic(DROPIN, plan["dropin_text"].encode(), 0o644)
                if labels:
                    self.command("/usr/sbin/restorecon", "-F", "--", self.path(DROPIN))
                    fd = os.open(self.path(DROPIN), os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                record["status"] = "staged"
                self.save_receipt(receipt, record)
            except Exception as error:
                try:
                    if changed:
                        self.restore(record, backup)
                    record["status"] = "rolled_back_after_error"
                    record["error"] = str(error)
                    self.save_receipt(receipt, record)
                except Exception as recovery:
                    raise InstallError(f"staging failed; rollback needs receipt {receipt}: {recovery}") from error
                raise InstallError(f"staging failed and drop-in restored; receipt: {receipt}: {error}") from error
        return {"action": "staged", "receipt": receipt,
                "private_executable": plan["private_executable"], "service_action": plan["service_action"]}

    def load_receipt(self, receipt):
        # Receipt locations and all write destinations are derived, not trusted from JSON.
        logical = str(receipt)
        match = re.fullmatch(re.escape(STATE) + r"/receipts/([0-9a-f]{32})/receipt\.json", logical)
        if not match:
            raise InstallError("receipt must be an installer-owned transaction under " + STATE)
        self.directory(str(Path(logical).parent), private=True)
        raw, _ = self.trusted(logical, private=True)
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("transaction") != match[1] or record.get("dropin") != DROPIN
                or record.get("status") not in ("prepared", "staged", "rolled_back", "rolled_back_after_error")):
            raise InstallError("invalid installer receipt")
        sha = record.get("candidate", {}).get("sha256", "")
        if (not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha)
                or record.get("private_executable") != f"{PRIVATE}/{sha}/sddm"
                or not isinstance(record.get("dropin_text"), str)
                or not isinstance(record.get("previous"), dict)
                or type(record["previous"].get("exists")) is not bool):
            raise InstallError("invalid receipt targets")
        previous = record["previous"]
        if previous["exists"]:
            if (previous.get("uid") != self.owner or type(previous.get("gid")) is not int
                    or type(previous.get("mode")) is not int
                    or not 0 <= previous["mode"] <= 0o7777 or previous["mode"] & 0o022
                    or not re.fullmatch("[0-9a-f]{64}", previous.get("sha256", ""))):
                raise InstallError("invalid previous drop-in metadata")
        return record, str(Path(logical).parent / "previous-dropin")

    def rollback(self, receipt, apply=False):
        if apply:
            native_preflight()
        record, backup = self.load_receipt(receipt)
        result = {"action": "plan-rollback", "receipt": str(receipt), "dropin": DROPIN,
                  "restore_previous": record["previous"]["exists"],
                  "retain_private_executable": record["private_executable"],
                  "service_action": "none; running SDDM is unchanged"}
        if record["previous"]["exists"]:
            saved, _ = self.trusted(backup, private=True)
            if digest(saved) != record["previous"]["sha256"]:
                raise InstallError("backup SHA256 mismatch")
        if not apply:
            return result
        with self.locked():
            record, backup = self.load_receipt(receipt)
            if record["status"] not in ("rolled_back", "rolled_back_after_error"):
                current = self.trusted(DROPIN, missing=True)
                installed = current is not None and current[0] == record["dropin_text"].encode()
                prior = (current is None and not record["previous"]["exists"]) or (
                    current is not None and record["previous"]["exists"]
                    and digest(current[0]) == record["previous"]["sha256"])
                if not installed and not (record["status"] == "prepared" and prior):
                    raise InstallError("drop-in changed since staging; refusing to overwrite it")
                self.restore(record, backup)
                record["status"] = "rolled_back"
                self.save_receipt(str(receipt), record)
            result["action"] = "rolled-back"
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--build-evidence", type=Path)
    parser.add_argument("--rollback", type=Path, metavar="RECEIPT")
    parser.add_argument("--apply", action="store_true", help="write files; never reload or restart a service")
    args = parser.parse_args(argv)
    if args.rollback:
        if any((args.source, args.expected_sha256, args.build_evidence)):
            parser.error("--rollback cannot be combined with candidate options")
    elif not all((args.source, args.expected_sha256, args.build_evidence)):
        parser.error("--source, --expected-sha256 and --build-evidence are required")
    try:
        installer = Installer()
        if args.rollback:
            result = installer.rollback(args.rollback, apply=args.apply)
        elif args.apply:
            result = installer.apply(args.source, args.expected_sha256, args.build_evidence)
        else:
            _, result = installer.plan(args.source, args.expected_sha256, args.build_evidence)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (InstallError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"install.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
