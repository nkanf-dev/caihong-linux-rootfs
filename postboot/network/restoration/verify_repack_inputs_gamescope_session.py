#!/usr/bin/env python3
"""Validate the exact 44-member package archive before native rpmbuild."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import tarfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-dir", type=Path, required=True,
                    help="private directory containing the reconstructed source archive")
args = parser.parse_args()
record = json.loads((root / "PROVENANCE-gamescope-session.json").read_text())
archive = args.source_dir / record["source_archive"]
assert hashlib.sha256(archive.read_bytes()).hexdigest() == record["source_archive_sha256"]
assert hashlib.sha256((root / record["spec"]).read_bytes()).hexdigest() == record["spec_sha256"]
expected = {item["path"]: item for item in record["archive_members"]}
with tarfile.open(archive, "r:gz") as source:
    members = source.getmembers()
    assert len(members) == len(expected)
    assert len({item.name for item in members}) == len(members)
    assert {item.name for item in members} == set(expected)
    for member in members:
        path = PurePosixPath(member.name)
        assert not path.is_absolute() and ".." not in path.parts
        assert member.isfile() or member.isdir() or member.issym()
        target = expected[member.name]
        assert oct(member.mode & 0o777) == target["mode"], member.name
        assert member.uid == 0 and member.gid == 0
        if member.isfile():
            assert target["kind"] == "file"
            data = source.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest() == target["sha256"], member.name
            assert len(data) == target["size"], member.name
        elif member.issym():
            assert target["kind"] == "symlink"
            assert member.linkname == target["target"]
            assert not PurePosixPath(member.linkname).is_absolute()
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
            assert resolved == target["resolved_target"]
            assert expected[resolved]["kind"] == "file"
        else:
            assert target["kind"] == "directory"
print("PASS: source/spec digests and all {} safe ownership-filtered archive members".format(len(expected)))
