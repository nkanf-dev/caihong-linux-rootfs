#!/usr/bin/env python3
"""Audit allowlisted preservation text. Findings print paths and rules, not values."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "postboot/archive-allowlist.json"
MAX_BYTES = 512 * 1024
FORBIDDEN_PARTS = {"node_modules", "vendor", "prefix", "pfx", "compatdata", ".git", "private", "local", "__pycache__"}
FORBIDDEN_SUFFIXES = {".so", ".apk", ".img", ".qcow2", ".core", ".o", ".a", ".dll", ".exe", ".pyc", ".png", ".jpg", ".7z", ".zip", ".gz", ".bin"}
RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "bearer-value": re.compile(r"(?i)bearer\s+[A-Za-z0-9_./+\-=]{12,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "steam-account-id": re.compile(r"\b7656119\d{10}\b"),
    "uuid": re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "private-ipv4": re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    "device-mac": re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
    "personal-home": re.compile(r"/(?:Users|var/home)/[A-Za-z0-9_.-]+"),
    "assessment-workspace": re.compile(r"caihong-" + r"assessment|/tmp/caihong-alvr-vulkan-headers\.tar\.gz"),
    "url-credentials": re.compile(r"https?://[^\s/]+:[^\s/@]+@"),
    "url-secret-query": re.compile(r"(?i)https?://[^\s]+[?&](?:token|key|auth|subscription|password)=[^\s>]+"),
}

# Credential-bearing YAML/JSON lines must use local placeholders, empty values, or env lookups.
ASSIGNMENT = re.compile(r"(?im)^\s*[\"']?(?:password|passwd|secret|uuid|authorization|subscription_url|api_key|access_token|refresh_token)[\"']?\s*[:=]\s*(.+)$")
PLACEHOLDER = re.compile(r"(?i)REPLACE|CHANGEME|<[^>]+>|\$\{|getenv|environ|args\.|None|null|^(?:true|false)[,\s]*$|^['\"]{2}[,\s]*$|^\[\]$|placeholder|read_text|credential-assignment|re\.compile|settings\.get")

def findings(path, data):
    errors = []
    pure = Path(path)
    if any(part in FORBIDDEN_PARTS for part in pure.parts) or pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        errors.append("forbidden-artifact-path")
    if len(data) > MAX_BYTES:
        errors.append("size-limit")
    if b"\0" in data:
        errors.append("binary-content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return errors + ["non-utf8"]
    for name, pattern in RULES.items():
        if pattern.search(text):
            errors.append(name)
    for match in ASSIGNMENT.finditer(text):
        if not PLACEHOLDER.search(match.group(1)):
            errors.append("credential-assignment")
    return sorted(set(errors))

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--staged", action="store_true", help="Audit the Git index, including unexpected staged paths")
    a = p.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    allowed = {row["path"]: row for row in manifest["files"]}
    allowed["postboot/archive-allowlist.json"] = {}
    allowed["docs/superpowers/plans/2026-10-21-postboot-pcvr-preservation.md"] = {}
    if a.staged:
        names = git("diff", "--cached", "--name-only", "-z").decode().split("\0")
        paths = [n for n in names if n]
    else:
        paths = [str(p.relative_to(ROOT)) for p in (ROOT / "postboot").rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts]
    bad = []
    total = 0
    for name in sorted(paths):
        if name not in allowed:
            bad.append((name, ["not-allowlisted"]))
            continue
        file = ROOT / name
        if file.is_symlink():
            bad.append((name, ["symlink"]))
            continue
        data = git("show", ":" + name) if a.staged else file.read_bytes()
        total += len(data)
        issues = findings(name, data)
        expected = allowed[name].get("sha256")
        if expected and hashlib.sha256(data).hexdigest() != expected:
            issues.append("allowlist-digest-mismatch")
        if issues:
            bad.append((name, issues))
    for name, issues in bad:
        print(name + ": " + ", ".join(issues))
    print(json.dumps({"files": len(paths), "bytes": total, "findings": len(bad), "staged": a.staged}))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
