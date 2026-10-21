#!/usr/bin/env python3
"""Plan, apply, or roll back exact Caihong package holds. File operations only."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import stat

CONFIG = Path('/etc/dnf/dnf.conf')
BACKUPS = Path('/var/lib/caihong/package-hold-backups')
CUSTOM = tuple("""armada-aurora armada-jupiter-hw-support armada-rgb armada-splash
fex-emu fex-emu-devel fex-emu-filesystem fex-emu-thunks fex-emu-utils
gamescope-session gamescope-session-steam inputplumber kwin kwin-common kwin-libs
lepton-armada lepton-guestos mangohud NetworkManager NetworkManager-cloud-setup
NetworkManager-libnm NetworkManager-tui NetworkManager-wifi
plasma-lookandfeel-fedora-mobile plasma-mobile powerdevil protontricks scx-scheds
steamos-manager terra-gamescope terra-gamescope-libs umtp-responder wpa_supplicant""".split())
MESA_BASELINE = tuple('mesa-dri-drivers mesa-filesystem mesa-libEGL mesa-libGL mesa-libgbm mesa-vulkan-drivers'.split())
HOLDS = tuple(sorted(CUSTOM + MESA_BASELINE))

class HoldError(RuntimeError):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest()

def require_native_root():
    if platform.system() != 'Linux' or os.geteuid() != 0:
        raise HoldError('--apply requires native Linux root')

def parent_fd(path, require_root=True, create=False, private=False):
    """Pin each directory with no-follow opens. Caller closes returned fd."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise HoldError('An absolute path without .. is required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=fd)
                os.fsync(fd)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if require_root and (info.st_uid != 0 or info.st_mode & 0o022):
                raise HoldError('Directory must be root-owned and not group/world writable')
            if private and index == len(parts)-1 and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise HoldError('Backup directory must be operator-owned mode 0700')
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_file(fd, name, require_root=True, private=False):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(handle)
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or mode & 0o7022:
            raise HoldError('Expected a single-link regular file without set-id or writable group/other bits')
        if require_root and info.st_uid != 0:
            raise HoldError('File must be root-owned')
        if private and mode != 0o600:
            raise HoldError('Private record must have mode 0600')
        with os.fdopen(os.dup(handle), 'rb') as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise HoldError('File exceeds 1 MiB')
        xattrs = {name: base64.b64encode(os.getxattr(handle, name)).decode('ascii') for name in os.listxattr(handle)} if hasattr(os, 'listxattr') else {}
        metadata = {'mode': mode, 'uid': info.st_uid, 'gid': info.st_gid, 'atime_ns': info.st_atime_ns, 'mtime_ns': info.st_mtime_ns, 'xattrs': xattrs}
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        return data, metadata, identity
    finally:
        os.close(handle)

def transform(data):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise HoldError('Config must be UTF-8') from error
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in text else '\n'
    section = None
    main_count = 0
    main_end = len(lines)
    main_start = None
    assignments = []
    alias_found = False
    for index, line in enumerate(lines):
        clean = line.rstrip('\r\n')
        header = re.fullmatch(r'\s*\[([^]]+)\]\s*(?:[#;].*)?', clean)
        if header:
            if section == 'main':
                main_end = index
            section = header.group(1)
            if section == 'main':
                main_count += 1
                main_start = index
            continue
        if section == 'main':
            if re.match(r'^[ \t]*exclude[ \t]*=', clean, re.I):
                alias_found = True
            match = re.fullmatch(r'([ \t]*excludepkgs[ \t]*=[ \t]*)(.*)', clean, re.I)
            if match:
                assignments.append((index, match))
    if alias_found:
        raise HoldError('A main exclude alias requires manual precedence review')
    if main_count != 1 or len(assignments) > 1:
        raise HoldError('Expected one [main] section and at most one excludepkgs assignment')
    existing = []
    if assignments:
        index, match = assignments[0]
        value = match.group(2)
        if any(c in value for c in '#;\\'):
            raise HoldError('Inline comments/continuations in excludepkgs need manual review')
        if index + 1 < len(lines) and re.match(r'^[ \t]+[^#;\s]', lines[index+1]):
            raise HoldError('Indented continuation after excludepkgs needs manual review')
        existing = [x for x in re.split(r'[ \t,]+', value.strip()) if x]
    missing = [name for name in HOLDS if name not in existing]
    if not missing:
        return data, existing
    if assignments:
        index, match = assignments[0]
        line = lines[index]
        ending = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
        old_value = match.group(2)
        separator = '' if not old_value else '' if old_value.endswith((' ', '\t', ',')) else ','
        lines[index] = match.group(1) + old_value + separator + ','.join(missing) + ending
    else:
        if main_end and not lines[main_end-1].endswith(('\n','\r')):
            lines[main_end-1] += newline
        lines.insert(main_end, 'excludepkgs=' + ','.join(HOLDS) + newline)
    return ''.join(lines).encode('utf-8'), existing

def write_new(fd, name, data):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(os.dup(handle), 'wb') as stream:
            stream.write(data)
            stream.flush()
        os.fsync(handle)
    finally:
        os.close(handle)

def replace(fd, name, data, metadata):
    temp = '.caihong-hold-' + secrets.token_hex(12)
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        if os.geteuid() == 0:
            os.fchown(handle, metadata['uid'], metadata['gid'])
        os.fchmod(handle, metadata['mode'])
        with os.fdopen(os.dup(handle), 'wb') as stream:
            stream.write(data)
            stream.flush()
        for key, value in metadata['xattrs'].items():
            os.setxattr(handle, key, base64.b64decode(value, validate=True))
        os.utime(handle, ns=(metadata['atime_ns'], metadata['mtime_ns']))
        os.fsync(handle)
        os.close(handle)
        handle = -1
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        if handle >= 0:
            os.close(handle)
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass

def summary(config, data, updated, existing):
    return {'config': str(config), 'action': 'none' if data == updated else 'add-exact-holds', 'sha256_before': digest(data), 'sha256_after': digest(updated), 'existing_exclusions': existing, 'custom_package_holds': list(CUSTOM), 'mesa_generic_baseline_holds': list(MESA_BASELINE), 'mesa_status': 'Current generic baseline held; Armada restoration pending', 'exact_added_names': [name for name in HOLDS if name not in existing], 'applied': False}

def manage(config=CONFIG, backups=BACKUPS, apply=False, require_root=True):
    config = Path(config)
    fd = parent_fd(config.parent, require_root)
    backup_fd = None
    operation_fd = None
    try:
        data, metadata, identity = read_file(fd, config.name, require_root)
        updated, existing = transform(data)
        result = summary(config, data, updated, existing)
        if not apply or data == updated:
            return result
        backup_fd = parent_fd(backups, require_root, create=True, private=True)
        fcntl.flock(backup_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        operation = 'hold-' + secrets.token_hex(12)
        os.mkdir(operation, 0o700, dir_fd=backup_fd)
        operation_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=backup_fd)
        fcntl.flock(operation_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = dict(result, version=1, metadata_before=metadata)
        write_new(operation_fd, 'original.conf', data)
        write_new(operation_fd, 'receipt.json', json.dumps(receipt, indent=2, sort_keys=True).encode())
        os.fsync(operation_fd)
        os.fsync(backup_fd)
        current, _, current_identity = read_file(fd, config.name, require_root)
        if current != data or current_identity != identity:
            raise HoldError('Config changed after backup; no config write was made')
        # No shared CAS lock exists with DNF or other root writers. Use a quiet window.
        replace(fd, config.name, updated, metadata)
        result.update(applied=True, receipt=str(Path(backups)/operation/'receipt.json'))
        return result
    finally:
        for handle in (operation_fd, backup_fd, fd):
            if handle is not None:
                os.close(handle)

def rollback(receipt_path, apply=False, require_root=True):
    receipt_path = Path(receipt_path)
    if receipt_path.name != 'receipt.json' or not re.fullmatch(r'hold-[0-9a-f]{24}', receipt_path.parent.name):
        raise HoldError('Expected a generated hold receipt path')
    root_fd = parent_fd(receipt_path.parent.parent, require_root, private=True)
    backup_fd = None
    fd = None
    try:
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backup_fd = parent_fd(receipt_path.parent, require_root, private=True)
        fcntl.flock(backup_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt_data, _, _ = read_file(backup_fd, receipt_path.name, require_root, private=True)
        receipt = json.loads(receipt_data)
        if receipt.get('version') != 1:
            raise HoldError('Unknown receipt format')
        original, _, _ = read_file(backup_fd, 'original.conf', require_root, private=True)
        if digest(original) != receipt['sha256_before']:
            raise HoldError('Backup hash does not match receipt')
        expected, _ = transform(original)
        if digest(expected) != receipt['sha256_after']:
            raise HoldError('Receipt does not describe this exact hold transform')
        config = Path(receipt['config'])
        fd = parent_fd(config.parent, require_root)
        current, _, identity = read_file(fd, config.name, require_root)
        if current == original:
            return {'action': 'none', 'reason': 'Original config already restored', 'applied': False}
        if current != expected:
            raise HoldError('Config changed after apply; refusing to overwrite newer settings')
        result = {'action': 'rollback', 'config': str(config), 'sha256_before': digest(current), 'sha256_after': digest(original), 'applied': False}
        if apply:
            again, _, again_identity = read_file(fd, config.name, require_root)
            if again != current or again_identity != identity:
                raise HoldError('Config changed during rollback review')
            replace(fd, config.name, original, receipt['metadata_before'])
            result['applied'] = True
        return result
    finally:
        if fd is not None:
            os.close(fd)
        if backup_fd is not None:
            os.close(backup_fd)
        os.close(root_fd)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--backups', type=Path, default=BACKUPS)
    parser.add_argument('--rollback', type=Path, metavar='RECEIPT')
    args = parser.parse_args()
    try:
        if args.apply:
            require_native_root()
        result = rollback(args.rollback, args.apply) if args.rollback else manage(args.config, args.backups, args.apply)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (HoldError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'error': str(error)}, indent=2))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
