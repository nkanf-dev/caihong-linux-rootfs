#!/usr/bin/env python3
"""Reject protected Armada package changes during offline image assembly."""
import argparse
import configparser
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FIELDS = ('name', 'epoch', 'version', 'release', 'arch', 'vendor', 'source_rpm', 'payload_digest')
QUERY_FORMAT = '%{NAME}\t%{EPOCH}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{VENDOR}\t%{SOURCERPM}\t%{PAYLOADDIGEST}\n'

class BaselineError(RuntimeError):
    pass

def lock_module():
    """Reuse the reviewed lock transform and atomic metadata writer."""
    source = Path(__file__).resolve().parents[1] / 'locks/lock_caihong_custom_packages.py'
    spec = importlib.util.spec_from_file_location('caihong_hold_policy', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def protected_names(policy_file):
    """Use the existing lock helper as the only authored package-name list."""
    names = tuple(lock_module().HOLDS)
    if len(names) != 39 or len(set(names)) != 39 or any(not re.fullmatch(r'[A-Za-z0-9+_.-]+', name) for name in names):
        raise BaselineError('The canonical hold policy must contain 39 unique exact package names')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(Path(policy_file).read_text())
        value = parser.get('main', 'excludepkgs')
    except (configparser.Error, OSError) as error:
        raise BaselineError('Cannot read canonical DNF hold policy: ' + str(error)) from error
    tokens = [token for token in re.split(r'[\s,]+', value.strip()) if token]
    if len(tokens) != 39 or set(tokens) != set(names):
        raise BaselineError('Canonical DNF excludepkgs differs from the 39 exact lock-helper names')
    return names

def parse_rows(output):
    rows = {}
    for line in output.splitlines():
        values = line.split('\t')
        if len(values) != len(FIELDS):
            raise BaselineError('Malformed native RPM query row')
        row = dict(zip(FIELDS, values))
        row['epoch'] = '0' if row['epoch'] in ('(none)', '(null)', '') else row['epoch']
        if not row['name'] or not row['epoch'].isdigit():
            raise BaselineError('Invalid package name or epoch in native RPM query')
        rows.setdefault(row['name'], []).append(row)
    return rows

def query_root(root, run=subprocess.run):
    root = Path(root).resolve()
    if root == Path('/') or not root.is_dir():
        raise BaselineError('Expected an offline build root, not /')
    result = run(['chroot', str(root), '/usr/bin/rpm', '-qa', '--qf', QUERY_FORMAT],
                 capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise BaselineError('Native target RPM query failed: ' + result.stderr.strip())
    return parse_rows(result.stdout)

def select_custom(rows, names):
    selected = {}
    errors = []
    for name in names:
        candidates = rows.get(name, [])
        if len(candidates) != 1:
            errors.append(name + ': expected one installed package, found ' + str(len(candidates)))
            continue
        row = candidates[0]
        if row['vendor'] != 'Armada' and '.armada' not in row['release']:
            errors.append(name + ': baseline is not an Armada/custom build (' + row['version'] + '-' + row['release'] + ', vendor=' + row['vendor'] + ')')
        elif not re.fullmatch(r'[0-9a-fA-F]{64}', row['payload_digest']):
            errors.append(name + ': missing SHA256 package payload identity')
        else:
            selected[name] = row
    if errors:
        raise BaselineError('Invalid original Armada baseline:\n  ' + '\n  '.join(errors))
    return selected

def capture(rows, names, image_digest):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_digest):
        raise BaselineError('Expected the exact resolved OCI SHA256 digest')
    return {'version': 1, 'image_digest': image_digest, 'protected_names': sorted(names),
            'packages': select_custom(rows, names)}

def compare(baseline, rows, names, image_digest):
    if baseline.get('version') != 1 or baseline.get('image_digest') != image_digest:
        raise BaselineError('Baseline format or resolved OCI digest does not match this build')
    if baseline.get('protected_names') != sorted(names) or set(baseline.get('packages', {})) != set(names):
        raise BaselineError('Baseline package set differs from the canonical 39-name policy')
    # Validate the stored baseline too: a generic snapshot must never waive this gate.
    select_custom({name: [row] for name, row in baseline['packages'].items()}, names)
    errors = []
    for name in names:
        current = rows.get(name, [])
        expected = baseline['packages'][name]
        if len(current) != 1:
            errors.append(name + ': expected one original package, found ' + str(len(current)))
        elif current[0] != expected:
            fields = [field + '=' + repr(expected[field]) + ' -> ' + repr(current[0][field]) for field in FIELDS if expected[field] != current[0][field]]
            errors.append(name + ': ' + '; '.join(fields))
    if errors:
        raise BaselineError('Protected Armada packages changed during image assembly:\n  ' + '\n  '.join(errors) + '\nUse matching Armada development RPMs or an isolated camera builder. Do not publish this rootfs or bypass the hold with generic replacements.')


def merge_policy(root, names):
    """Merge holds into only the offline target config; keep upstream defaults."""
    root = Path(root).absolute()
    if root == Path('/') or not root.is_dir() or '..' in root.parts:
        raise BaselineError('Expected an offline build root, not /')
    lock = lock_module()
    config = root / 'etc/dnf/dnf.conf'
    # Build checkout ancestors may belong to the builder user. Each directory
    # is still pinned no-follow; the target config must be safe and root-owned.
    fd = lock.parent_fd(config.parent, require_root=False)
    try:
        original, metadata, identity = lock.read_file(fd, config.name, require_root=True)
        updated, _ = lock.transform(original)
        if updated != original:
            current, _, current_identity = lock.read_file(fd, config.name, require_root=True)
            if current != original or current_identity != identity:
                raise BaselineError('Offline DNF config changed during policy merge')
            lock.replace(fd, config.name, updated, metadata)
        actual, _, _ = lock.read_file(fd, config.name, require_root=True)
        _, existing = lock.transform(actual)
        if not set(names).issubset(existing):
            raise BaselineError('Offline DNF config is missing required exact holds')
        return updated != original
    except lock.HoldError as error:
        raise BaselineError('Cannot merge offline DNF policy: ' + str(error)) from error
    finally:
        os.close(fd)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'check', 'merge-policy'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--image-digest', required=True)
    args = parser.parse_args()
    try:
        names = protected_names(args.policy)
        if args.operation == 'merge-policy':
            changed = merge_policy(args.root, names)
            print('PASS: offline DNF policy merged; ' + ('updated' if changed else 'already complete'))
            return 0
        rows = query_root(args.root)
        if args.operation == 'capture':
            baseline = capture(rows, names, args.image_digest)
            # Exclusive creation prevents accidentally replacing an earlier baseline.
            with args.baseline.open('x') as stream:
                json.dump(baseline, stream, indent=2, sort_keys=True)
                stream.write('\n')
        else:
            compare(json.loads(args.baseline.read_text()), rows, names, args.image_digest)
        print('PASS: 39 original custom-package identities and payload digests ' + args.operation)
        return 0
    except (BaselineError, OSError, ValueError, KeyError) as error:
        print('Armada package baseline: ' + str(error), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
