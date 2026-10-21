#!/usr/bin/env python3
"""Check authored Python/JSON/XML/shell/JS without executing application code."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

EXCLUDED = {"node_modules", "__pycache__", ".git", "dist"}

def sources(root):
    root = Path(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_file() and not path.is_symlink():
                yield path

def check_sources(root):
    counts = {"python": 0, "json": 0, "xml": 0, "shell": 0, "javascript": 0}
    for path in sources(root):
        suffix = path.suffix
        if suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
            counts["python"] += 1
        elif suffix == ".json":
            json.loads(path.read_text())
            counts["json"] += 1
        elif suffix == ".xml":
            ET.parse(path)
            counts["xml"] += 1
        elif suffix == ".sh":
            subprocess.run(["bash", "-n", str(path)], check=True)
            counts["shell"] += 1
        elif suffix in (".js", ".mjs", ".cjs"):
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node is required for JavaScript syntax checks")
            subprocess.run([node, "--check", str(path)], check=True)
            counts["javascript"] += 1
    return counts

if __name__ == "__main__":
    print(json.dumps(check_sources(Path(__file__).resolve().parents[1])))
