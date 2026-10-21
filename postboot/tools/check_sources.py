#!/usr/bin/env python3
"""Parse Python, validate JSON/XML, and check shell/JS syntax without executing."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
counts = {"python": 0, "json": 0, "xml": 0, "shell": 0, "javascript": 0}
for path in sorted(root.rglob("*")):
    if not path.is_file() or "__pycache__" in path.parts:
        continue
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
print(json.dumps(counts))
