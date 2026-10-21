#!/usr/bin/env python3
"""Build an ALVR SetValues payload after checking it against a local session.

This tool emits JSON only. It never contacts the dashboard or changes settings.
"""
import argparse
import json
from pathlib import Path

def request(profile, session):
    result = []
    for key, value in profile["values"].items():
        parts = key.split(".")
        node = session
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                raise ValueError("Session schema is missing " + key)
            node = node[part]
        if isinstance(node, bool):
            valid = isinstance(value, bool)
        elif isinstance(node, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(node, float):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = type(node) is type(value)
        if not valid:
            raise ValueError("Value type differs from existing session: " + key)
        result.append({"path": [{"Name": p} for p in parts], "value": value})
    return {"SetValues": result}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("profile", type=Path)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    payload = request(json.loads(a.profile.read_text()), json.loads(a.session.read_text()))
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.write_text(json.dumps(payload, indent=2) + "\n")
    a.output.chmod(0o600)
    print("Wrote settings-only SetValues payload")

if __name__ == "__main__":
    main()
