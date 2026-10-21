"""Shared source-integrity and output-boundary helpers (Python standard library)."""
import hashlib
import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPOSITORY = next((parent for parent in HERE.parents if (parent / ".git").exists()), HERE.parent)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_manifest(name):
    return json.loads((HERE / name).read_text())


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("Unsafe manifest path: " + value)
    return Path(*path.parts)


def external_path(value):
    path = Path(value).expanduser().resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("Output/stage directory must be outside the repository: " + str(path))
    return path


def verify_record(data, record):
    if len(data) != record["size"] or sha256(data) != record["sha256"]:
        raise ValueError("Size/SHA256 mismatch: " + record["path"])
    expected_blob = record.get("git_blob", record.get("staged_git_blob"))
    if expected_blob and git_blob(data) != expected_blob:
        raise ValueError("Git blob mismatch: " + record["path"])


def verify_tree(root, records):
    seen = set()
    for record in records:
        rel = relative_path(record["path"])
        if rel in seen:
            raise ValueError("Duplicate manifest path: " + str(rel))
        seen.add(rel)
        target = root / rel
        if target.is_symlink() or root.resolve() not in target.resolve().parents:
            raise ValueError("Manifest file must be inside its root: " + str(target))
        verify_record(target.read_bytes(), record)


def verify_patch(path, expected):
    if sha256(path.read_bytes()) != expected:
        raise ValueError("Patch SHA256 mismatch: " + str(path))
