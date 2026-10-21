#!/usr/bin/env python3
"""Edit only the recorded DeckyClash compatibility switches; never start a service."""
import argparse
from collections.abc import MutableMapping
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

FILES = ("settings/DeckyClash/config.json", "plugins/DeckyClash/override.yaml")


def private_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Expected a regular, non-symlink local file")
    if path.stat().st_mode & 0o077:
        raise ValueError("Private config and backup files must have mode 0600")


def atomic_write(path, text):
    fd, name = tempfile.mkstemp(prefix=".caihong-", dir=path.parent)
    try:
        if path.exists():
            metadata = path.stat()
            os.fchown(fd, metadata.st_uid, metadata.st_gid)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict):
            if not isinstance(target.get(key), MutableMapping):
                target[key] = {}
            merge(target[key], value)
        else:
            target[key] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "enable-autostart", "disable-autostart", "restore"))
    parser.add_argument("--homebrew", type=Path, default=Path.home() / "homebrew")
    parser.add_argument("--backup-dir", type=Path, required=True,
                        help="new private directory for configure; existing one for restore")
    args = parser.parse_args()
    base = args.homebrew.expanduser().resolve(strict=True)
    backup = args.backup_dir.expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if backup == checkout or checkout in backup.parents:
        raise ValueError("Put private rollback files outside this checkout")
    paths = [base / name for name in FILES]
    if any(base not in path.resolve(strict=True).parents for path in paths):
        raise ValueError("Config path must stay inside homebrew")
    for path in paths:
        private_file(path)
    if args.action == "restore":
        saved = [backup / str(index) for index in range(len(paths))]
        for source in saved:
            private_file(source)
        for source, target in zip(saved, paths):
            atomic_write(target, source.read_text())
        print("Restored the two saved files. Services remain unchanged.")
        return
    settings = json.loads(paths[0].read_text())
    if not isinstance(settings, dict):
        raise ValueError("Expected a settings object")
    if args.action != "configure":
        # These actions require the original two-file rollback set to exist.
        for index in range(len(paths)):
            private_file(backup / str(index))
        settings["autostart"] = args.action == "enable-autostart"
        atomic_write(paths[0], json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
        print("Updated only autostart. Services remain unchanged.")
        return
    # Use the package's existing parser on the target, without copying its code.
    sys.path.insert(0, str(base / "plugins/DeckyClash/py_modules"))
    from ruamel.yaml import YAML
    from collections.abc import Mapping
    from io import StringIO
    yaml = YAML()
    override = yaml.load(paths[1].read_text())
    patch = yaml.load(Path(__file__).with_name("caihong-policy-tun.yaml").read_text())
    if not isinstance(override, Mapping) or not isinstance(patch, Mapping):
        raise ValueError("Expected override mappings")
    # Convert only the patch to plain dictionaries; preserve the installed mapping and comments.
    def plain(value):
        if isinstance(value, Mapping):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, list):
            return [plain(item) for item in value]
        return value
    merge(override, plain(patch))
    settings.update(autostart=False, skip_steam_download=False, allow_remote_access=False,
                    override_dns=True, enhanced_mode="fake-ip", log_level="INFO")
    buffer = StringIO()
    yaml.dump(override, buffer)
    # Validate everything before creating the one-time rollback set or changing files.
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(backup, 0o700)
    for index, source in enumerate(paths):
        fd = os.open(backup / str(index), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(source.read_text())
    atomic_write(paths[1], buffer.getvalue())
    atomic_write(paths[0], json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    print("Saved rollback files and merged compatibility switches with autostart off.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Parser and file exceptions may include private content. Print only the class.
        raise SystemExit("Local edit failed (" + type(error).__name__ + "). Check inputs privately.")
