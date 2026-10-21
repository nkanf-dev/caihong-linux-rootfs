#!/usr/bin/env python3
"""Preview a private launcher bundle, or explicitly apply/roll back a transaction.

Only this bundle and its private transaction state are written. Steam launch
options are printed for review; Steam configuration and processes are untouched.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import uuid

DEFAULT_STEAMVR_VK_DRIVER = "/usr/share/vulkan/icd.d/freedreno_icd.x86_64.json"
BUNDLE_RELATIVE = Path(".local/lib/caihong-vrchat-launcher")
STATE_RELATIVE = Path(".local/state/caihong-vrchat-launcher")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class InstallError(RuntimeError):
    """A fixed diagnostic that does not expose inherited arguments or environment."""


@dataclass(frozen=True)
class DeployFile:
    source: Path
    destination: Path
    data: bytes
    previous_sha256: object


@dataclass(frozen=True)
class InstallPlan:
    home: Path
    bundle: Path
    state: Path
    files: tuple


def _absolute(path):
    value = os.fspath(path)
    if not os.path.isabs(value) or any(c in value for c in "\x00\r\n"):
        raise InstallError("Paths must be absolute, single-line filesystem paths")
    return Path(os.path.abspath(value))


def _home(home):
    return _absolute(Path.home() if home is None else home)


def _inside(path, root):
    return path == root or root in path.parents


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def _directory(path, home, *, create=False, missing_ok=False):
    """Walk real directories with no-follow directory descriptors.

    Ancestors inside HOME must be owner-controlled. Managed bundle/state
    directories, including their descendants, must have exactly mode 0700.
    """
    path = _absolute(path)
    private_roots = (home / BUNDLE_RELATIVE, home / STATE_RELATIVE)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(path.anchor, flags)
        current = Path(path.anchor)
        for component in path.parts[1:]:
            current = current / component
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    if missing_ok:
                        yield None
                        return
                    raise InstallError("A required directory is missing") from None
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
                os.fchmod(child, 0o700)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if _inside(current, home):
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise InstallError("HOME and destination ancestors must be owner-controlled real directories")
            if any(_inside(current, root) for root in private_roots):
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise InstallError("Bundle and transaction directories must be owner-owned with mode 0700")
        yield descriptor
    except OSError:
        raise InstallError("A filesystem path is inaccessible or has a symlink or unsafe ancestor") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_at(directory, name, *, private=True):
    try:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise InstallError("Source and destination files must be real regular files, not symlinks")
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise InstallError("Existing destination and transaction files must be owner-owned with mode 0600")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise InstallError("A file changed while it was being checked")
        return source.read()


def _read(path, home, *, private=True):
    with _directory(path.parent, home, missing_ok=True) as descriptor:
        if descriptor is None:
            return None
        return _read_at(descriptor, path.name, private=private)


def _write(path, data, home, *, expected_sha256):
    """Replace one private file only if its current bytes still match the plan."""
    with _directory(path.parent, home, create=True) as directory:
        temporary = ".caihong-new-" + uuid.uuid4().hex
        created = False
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            created = True
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            current = _read_at(directory, path.name)
            actual = None if current is None else _sha(current)
            if actual != expected_sha256:
                raise InstallError("A destination changed; no user-edited file was overwritten")
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            created = False
            os.fsync(directory)
        finally:
            if created:
                os.unlink(temporary, dir_fd=directory)


def _remove(path, home, expected_sha256):
    with _directory(path.parent, home) as directory:
        current = _read_at(directory, path.name)
        if current is None or _sha(current) != expected_sha256:
            raise InstallError("A destination changed; no user-edited file was removed")
        os.unlink(path.name, dir_fd=directory)
        os.fsync(directory)


def _layout(home):
    # Check existing directories even if every deploy file is currently absent.
    for path in (home, home / BUNDLE_RELATIVE, home / STATE_RELATIVE):
        with _directory(path, home, missing_ok=path != home):
            pass


def _source_files(directory, home):
    with _directory(directory, home) as descriptor:
        return [directory / name for name in sorted(os.listdir(descriptor)) if name.endswith(".py")]


def plan_install(*, home=None, source_root=None):
    """Read current sources and destinations. Do not create any filesystem entry.

    source_root is the repository root, not the launcher subdirectory. All current
    top-level launcher/runtime *.py files are discovered on each invocation.
    """
    home = _home(home)
    root = _absolute(Path(__file__).absolute().parents[2] if source_root is None else source_root)
    bundle, state = home / BUNDLE_RELATIVE, home / STATE_RELATIVE
    _layout(home)
    source_pairs = [(source, bundle / source.name)
                    for source in _source_files(root / "postboot/launcher", home)]
    route = root / "postboot/vrchat/launch_vrchat_known_route.py"
    source_pairs.append((route, bundle / "vrchat" / route.name))
    source_pairs.extend((source, bundle / "runtime" / source.name)
                        for source in _source_files(root / "postboot/pcvr/runtime", home))
    files = []
    for source, destination in sorted(source_pairs, key=lambda pair: str(pair[1])):
        data = _read(source, home, private=False)
        if data is None:
            raise InstallError("A required launcher source file is missing")
        previous = _read(destination, home)
        files.append(DeployFile(source, destination, data, None if previous is None else _sha(previous)))
    if not files:
        raise InstallError("No launcher source files were found")
    return InstallPlan(home, bundle, state, tuple(files))


def launch_options(*, home=None, steamvr_vk_driver=DEFAULT_STEAMVR_VK_DRIVER):
    """Return app-scoped templates. Do not change the process environment."""
    home = _home(home)
    driver = _absolute(steamvr_vk_driver)
    bundle = home / BUNDLE_RELATIVE
    prefix = home / ".local/share/cvrc-x64"
    commands = {
        "438100": ["env", "STEAM_COMPAT_DATA_PATH=" + str(prefix),
                   "EAC_LAUNCHERDIR=" + str(prefix / "pfx/drive_c/users/steamuser/AppData/Roaming/EasyAntiCheat"),
                   "PROTON_EAC_RUNTIME=" + str(home / ".local/share/Steam/steamapps/common/Proton EasyAntiCheat Runtime"),
                   "WINEDEBUG=-all", "PROTON_USE_XALIA=0",
                   "python3", str(bundle / "dual_mode.py"), "--mode", "auto", "--", "%command%",
                   "--enable-avpro-in-proton"],
        "250820": ["env", "FEX_APP_CONFIG=" + str(home / ".local/state/caihong-pcvr/server-fex-config.json"),
                   "VK_DRIVER_FILES=" + str(driver), "python3", str(bundle / "steamvr_auto.py"), "--", "%command%"],
    }
    return {appid: " ".join(shlex.quote(word) for word in words) for appid, words in commands.items()}


def _save_manifest(path, manifest, home):
    previous = _read(path, home)
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write(path, data, home, expected_sha256=None if previous is None else _sha(previous))


def install(plan, *, apply=False):
    """Return a new manifest Path on apply, or None for a read-only dry run."""
    home = plan.home
    _layout(home)
    originals = []
    for item in plan.files:
        if not _allowed_destination(item.destination, plan.bundle):
            raise InstallError("An installation destination is outside the launcher bundle")
        previous = _read(item.destination, home)
        if (None if previous is None else _sha(previous)) != item.previous_sha256:
            raise InstallError("A destination changed after planning; no installation was started")
        originals.append(previous)
    if not apply:
        return None
    transaction = plan.state / "transactions" / uuid.uuid4().hex
    manifest_path = transaction / "manifest.json"
    entries = []
    for index, (item, previous) in enumerate(zip(plan.files, originals)):
        backup = transaction / "backups" / (str(index).zfill(4) + ".bak") if previous is not None else None
        if backup is not None:
            _write(backup, previous, home, expected_sha256=None)
        entries.append({"source": str(item.source), "destination": str(item.destination),
                        "existed": previous is not None, "installed_sha256": _sha(item.data),
                        "backup": None if backup is None else str(backup),
                        "original_sha256": item.previous_sha256,
                        "original_mode": 0o600 if previous is not None else None})
    manifest = {"version": 1, "home": str(home), "bundle": str(plan.bundle),
                "status": "prepared", "files": entries}
    _save_manifest(manifest_path, manifest, home)
    try:
        for item in plan.files:
            _write(item.destination, item.data, home, expected_sha256=item.previous_sha256)
        manifest["status"] = "applied"
        _save_manifest(manifest_path, manifest, home)
    except (OSError, InstallError):
        try:
            rollback(manifest_path, home=home, apply=True)
        except (OSError, InstallError):
            raise InstallError("Installation stopped; review the saved transaction before retrying rollback") from None
        raise InstallError("Installation stopped and its unchanged files were rolled back") from None
    return manifest_path


def _allowed_destination(path, bundle):
    if not _inside(path, bundle) or path == bundle:
        return False
    parts = path.relative_to(bundle).parts
    if len(parts) == 1:
        return parts[0].endswith(".py")
    return len(parts) == 2 and ((parts[0] == "runtime" and parts[1].endswith(".py")) or
                              parts == ("vrchat", "launch_vrchat_known_route.py"))


def _load_manifest(path, home):
    path = _absolute(path)
    if path.name != "manifest.json":
        path = path / "manifest.json"
    state = home / STATE_RELATIVE
    if (path.parent.parent != state / "transactions" or
            re.fullmatch(r"[0-9a-f]{32}", path.parent.name) is None):
        raise InstallError("Rollback must select a transaction in this HOME's private launcher state")
    raw = _read(path, home)
    if raw is None:
        raise InstallError("The transaction manifest is missing")
    try:
        manifest = json.loads(raw)
        if (type(manifest) is not dict or manifest.get("version") != 1 or
                manifest.get("home") != str(home) or manifest.get("bundle") != str(home / BUNDLE_RELATIVE) or
                manifest.get("status") not in ("prepared", "applied", "rolling-back", "rolled-back") or
                type(manifest.get("files")) is not list or not manifest["files"]):
            raise ValueError
        seen = set()
        for index, entry in enumerate(manifest["files"]):
            destination = _absolute(entry["destination"])
            if (str(destination) != entry["destination"] or destination in seen or
                    not _allowed_destination(destination, home / BUNDLE_RELATIVE) or
                    type(entry["existed"]) is not bool or
                    not isinstance(entry["installed_sha256"], str) or not DIGEST.fullmatch(entry["installed_sha256"])):
                raise ValueError
            seen.add(destination)
            if entry["existed"]:
                expected_backup = path.parent / "backups" / (str(index).zfill(4) + ".bak")
                if (entry["backup"] != str(expected_backup) or entry["original_mode"] != 0o600 or
                        not isinstance(entry["original_sha256"], str) or not DIGEST.fullmatch(entry["original_sha256"])):
                    raise ValueError
            elif any(entry.get(key) is not None for key in ("backup", "original_sha256", "original_mode")):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise InstallError("The transaction manifest has invalid paths or metadata") from None
    return path, manifest


def rollback(manifest_path, *, home=None, apply=False):
    """Preview or apply all-or-nothing conflict checks; never remove directories.

    A changed/missing installed file blocks an applied transaction's rollback.
    Prepared transactions also permit untouched originals after interrupted apply.
    Backups and the manifest remain available after rollback.
    """
    home = _home(home)
    _layout(home)
    path, manifest = _load_manifest(manifest_path, home)
    if manifest["status"] == "rolled-back":
        return ()
    operations = []
    for entry in manifest["files"]:
        destination = Path(entry["destination"])
        current = _read(destination, home)
        current_sha = None if current is None else _sha(current)
        original = None
        if entry["existed"]:
            original = _read(Path(entry["backup"]), home)
            if original is None or _sha(original) != entry["original_sha256"]:
                raise InstallError("An original backup is missing or changed; rollback made no changes")
        if current_sha == entry["installed_sha256"]:
            operations.append((destination, original, entry["installed_sha256"]))
        elif manifest["status"] in ("prepared", "rolling-back") and current_sha == entry["original_sha256"]:
            continue
        else:
            raise InstallError("An installed file changed or is missing; rollback made no changes")
    if apply:
        manifest["status"] = "rolling-back"
        _save_manifest(path, manifest, home)
        for destination, original, expected in reversed(operations):
            if original is None:
                _remove(destination, home, expected)
            else:
                _write(destination, original, home, expected_sha256=expected)
        manifest["status"] = "rolled-back"
        _save_manifest(path, manifest, home)
    return tuple(operation[0] for operation in operations)


def main(argv=None, *, home=None, source_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Make the reviewed install or rollback changes")
    parser.add_argument("--rollback", metavar="TRANSACTION", type=Path,
                        help="Preview rollback of a manifest or transaction directory; add --apply to restore")
    parser.add_argument("--steamvr-vk-driver", default=DEFAULT_STEAMVR_VK_DRIVER,
                        help="Absolute ICD path used only in the printed SteamVR launch option")
    args = parser.parse_args(argv)
    try:
        selected_home = _home(home)
        options = launch_options(home=selected_home, steamvr_vk_driver=args.steamvr_vk_driver)
        if args.rollback is not None:
            paths = rollback(args.rollback, home=selected_home, apply=args.apply)
            print(("Rolled back" if args.apply else "Dry run: would roll back") + " " + str(len(paths)) + " files.")
        else:
            plan = plan_install(home=selected_home, source_root=source_root)
            manifest = install(plan, apply=args.apply)
            if manifest is None:
                print("Dry run: would install " + str(len(plan.files)) + " launcher files. No files created.")
            else:
                print("Installed " + str(len(plan.files)) + " launcher files. Transaction: " + str(manifest))
        print("VRChat (438100) launch option:\n" + options["438100"])
        print("SteamVR (250820) launch option:\n" + options["250820"])
        return 0
    except (OSError, InstallError) as error:
        message = str(error) if isinstance(error, InstallError) else "A filesystem operation failed"
        print("Launcher installer: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
