#!/usr/bin/env python3
"""Create an offline compositor-profile candidate. Never edits the input."""
import argparse
import hashlib
import json
import os
from pathlib import Path

class ObjectPairs(list):
    pass

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def value_end(text, start):
    dec = json.JSONDecoder()
    return start + dec.raw_decode(text[start:])[1]

def config_bounds(text):
    """Find exactly one top-level Config object without normalizing duplicate keys."""
    dec = json.JSONDecoder()
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1
    if i == len(text) or text[i] != "{":
        raise ValueError("The profile must be a JSON object")
    i += 1
    matches = []
    while True:
        while text[i].isspace():
            i += 1
        if text[i] == "}":
            break
        key, n = dec.raw_decode(text[i:])
        if not isinstance(key, str):
            raise ValueError("Invalid JSON object key")
        i += n
        while text[i].isspace():
            i += 1
        if text[i] != ":":
            raise ValueError("Missing JSON colon")
        i += 1
        while text[i].isspace():
            i += 1
        end = value_end(text, i)
        if key == "Config":
            if text[i] != "{":
                raise ValueError("Config must be an object")
            matches.append((i, end))
        i = end
        while text[i].isspace():
            i += 1
        if text[i] == "}":
            break
        if text[i] != ",":
            raise ValueError("Missing JSON comma")
        i += 1
    if len(matches) != 1:
        raise ValueError("Expected exactly one top-level Config object")
    return matches[0]

def env_assignments(obj):
    if isinstance(obj, ObjectPairs):
        for key, value in obj:
            if key in ("Env", "HostEnv"):
                vals = value if isinstance(value, list) and not isinstance(value, ObjectPairs) else [value]
                for item in vals:
                    if isinstance(item, str):
                        yield item
            yield from env_assignments(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from env_assignments(value)

def generate(raw, mode):
    if mode not in ("flushall", "nomultipos"):
        raise ValueError("Unsupported probe")
    text = raw.decode("utf-8")
    parsed = json.loads(text, object_pairs_hook=ObjectPairs)
    if any(v.partition("=")[0] == "TU_DEBUG" for v in env_assignments(parsed)):
        raise ValueError("Existing TU_DEBUG requires operator review; no automatic merge")
    begin, end = config_bounds(text)
    body = text[begin + 1:end - 1]
    insertion = ("," if body.strip() else "") + '"HostEnv":' + json.dumps("TU_DEBUG=" + mode)
    candidate = (text[:end - 1] + insertion + text[end - 1:]).encode("utf-8")
    after = json.loads(candidate, object_pairs_hook=ObjectPairs)
    assignments = list(env_assignments(after))
    if assignments.count("TU_DEBUG=" + mode) != 1:
        raise ValueError("Candidate validation failed")
    if candidate[:len(text[:end - 1].encode())] != text[:end - 1].encode():
        raise ValueError("Unexpected prefix change")
    return candidate

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("flushall", "nomultipos"), default="flushall")
    args = parser.parse_args(argv)
    source = args.input.resolve(strict=True)
    if args.output.exists() or args.output.is_symlink():
        parser.error("Refusing to overwrite output")
    output = args.output.resolve()
    if not output.name.endswith(".candidate.json"):
        parser.error("Output filename must end with .candidate.json")
    for path in (args.output.absolute(), output):
        parts = tuple(part.casefold() for part in path.parts)
        if "appconfig" in parts[:-1]:
            parser.error("Output must be outside FEX AppConfig")
    if source == output:
        parser.error("Input and output must differ")
    if args.input.name != "vrcompositor.real.json":
        parser.error("Input must be an exported vrcompositor.real.json profile")
    if output.exists() or output.is_symlink():
        parser.error("Refusing to overwrite output")
    manifest_path = output.with_name(output.name + ".manifest.json")
    if manifest_path.exists() or manifest_path.is_symlink():
        parser.error("Refusing to overwrite manifest")
    raw = source.read_bytes()
    try:
        candidate = generate(raw, args.mode)
    except (ValueError, IndexError) as exc:
        parser.error(str(exc))
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(candidate)
    manifest = {"status": "offline_candidate_only", "input": str(source),
                "candidate": str(output), "input_sha256": digest(raw),
                "candidate_sha256": digest(candidate), "mode": args.mode,
                "scope": "exact FEX vrcompositor.real Config.HostEnv only",
                "live_changes": False}
    manifest_created = False
    try:
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        manifest_created = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
    except BaseException:
        output.unlink()
        if manifest_created:
            manifest_path.unlink()
        raise
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()
