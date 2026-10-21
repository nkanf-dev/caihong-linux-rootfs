#!/usr/bin/env python3
"""Route one reviewed VRChat Steam audio namespace to live ALVR endpoints."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

KINDS = ("sinks", "sources", "sink-inputs", "source-outputs", "clients")
VERSION = 1


class RouteError(RuntimeError):
    pass


class Pactl:
    """Native pactl adapter. Tests replace this entire adapter."""
    def __init__(self):
        self.env = dict(os.environ)
        runtime = "/run/user/" + str(os.getuid())
        self.env.update(XDG_RUNTIME_DIR=runtime, PIPEWIRE_RUNTIME_DIR=runtime,
                        PULSE_SERVER="unix:" + runtime + "/pulse/native")

    def run(self, args):
        try:
            result = subprocess.run(["pactl"] + args, env=self.env, text=True,
                                    capture_output=True, timeout=10, check=False)
            return {"returncode": result.returncode, "stdout": result.stdout,
                    "stderr": result.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"returncode": -1, "stdout": "", "stderr": str(exc)}

    def list(self, kind):
        result = self.run(["--format=json", "list", kind])
        if result["returncode"]:
            raise RouteError("pactl list " + kind + ": " + result["stderr"])
        try:
            values = json.loads(result["stdout"])
        except (ValueError, TypeError) as exc:
            raise RouteError("Invalid pactl JSON: " + kind) from exc
        if not isinstance(values, list) or not all(isinstance(x, dict) for x in values):
            raise RouteError("Expected pactl JSON object list: " + kind)
        return values

    def move(self, kind, index, target):
        command = {"sink-inputs": "move-sink-input", "source-outputs": "move-source-output"}[kind]
        return self.run([command, str(index), target])


def snapshot(backend):
    return {kind: backend.list(kind) for kind in KINDS}


def props(node):
    return node.get("properties", {})


def one(values, label):
    values = list(values)
    if len(values) != 1:
        raise RouteError("Expected exactly one " + label + "; found " + str(len(values)))
    return values[0]


def by_index(data, kind, index):
    return one((x for x in data[kind] if str(x.get("index")) == str(index)), kind + " index " + str(index))


def ref(node):
    p = props(node)
    if "index" not in node or not p.get("object.serial") or not p.get("object.id"):
        raise RouteError("Object lacks current index/serial/id")
    return {"index": node["index"], "serial": str(p["object.serial"]),
            "object_id": str(p["object.id"]), "name": node.get("name", p.get("node.name")),
            "node_name": p.get("node.name"), "media_class": p.get("media.class"),
            "media_name": p.get("media.name"),
            "client_object_id": p.get("client.id"),
            "group": p.get("session.audio-group"), "link_group": p.get("node.link-group"),
            "process_id": p.get("application.process.id"),
            "process_binary": p.get("application.process.binary"),
            "application_name": p.get("application.name"), "security_pid": p.get("pipewire.sec.pid"),
            "client_api": p.get("client.api")}


def owner(data, node, pid=None, binary=None, app_name=None):
    cid = props(node).get("client.id")
    if cid is None:
        raise RouteError("Node has no owning PipeWire client")
    client = one((x for x in data["clients"] if str(props(x).get("object.id")) == str(cid)),
                 "owner of node " + str(node.get("index")))
    p = props(client)
    if pid is not None and str(p.get("application.process.id")) != str(pid):
        raise RouteError("Unexpected owner PID for " + str(node.get("index")))
    if (pid is not None and p.get("client.api") != "pipewire-pulse"
            and p.get("pipewire.sec.pid") is not None and str(p["pipewire.sec.pid"]) != str(pid)):
        raise RouteError("Unexpected security PID for " + str(node.get("index")))
    if binary is not None and p.get("application.process.binary") != binary:
        raise RouteError("Unexpected owner binary for " + str(node.get("index")))
    if app_name is not None and p.get("application.name") != app_name:
        raise RouteError("Unexpected owner application for " + str(node.get("index")))
    return client


def discover(data, app_pid, server_pid):
    if app_pid <= 0 or server_pid <= 0 or app_pid == server_pid:
        raise RouteError("Require distinct positive reviewed app/server PIDs")
    app_nodes = []
    namespace = []
    for kind, field, endpoint_kind, klass in [
            ("sink-inputs", "sink", "sinks", "Audio/Sink"),
            ("source-outputs", "source", "sources", "Audio/Source")]:
        app = one((n for n in data[kind]
                   if props(n).get("application.name") == "VRChat.exe"
                   and str(props(n).get("application.process.id")) == str(app_pid)), "reviewed VRChat " + kind)
        owner(data, app, app_pid, app_name="VRChat.exe")
        device = by_index(data, endpoint_kind, app.get(field))
        p = props(device)
        group = p.get("session.audio-group", "")
        if not re.fullmatch(r"pw-audio-namespace\.[1-9][0-9]*", group):
            raise RouteError("VRChat endpoint is not a Steam audio namespace")
        if device.get("name") != "device.audio_group:" + group or p.get("media.class") != klass:
            raise RouteError("Unexpected namespace endpoint")
        if not p.get("node.link-group"):
            raise RouteError("Namespace lacks loopback link group")
        owner(data, device, binary="wireplumber")
        # Avoid rerouting a namespace that currently serves another app.
        members = [n for n in data[kind] if str(n.get(field)) == str(device["index"])]
        if len(members) != 1 or members[0]["index"] != app["index"]:
            raise RouteError("Namespace has other current consumers/producers")
        app_nodes.append(app)
        namespace.append(device)
    group = props(namespace[0])["session.audio-group"]
    if props(namespace[1])["session.audio-group"] != group:
        raise RouteError("VRChat output and microphone namespace groups differ")
    moves = []
    identities = []
    for number, (kind, field, endpoint_kind, klass, alvr_name, media_name) in enumerate([
            ("sink-inputs", "sink", "sinks", "Stream/Output/Audio", "ALVR Audio", "alvr-audio"),
            ("source-outputs", "source", "sources", "Stream/Input/Audio", "ALVR Microphone", "alvr-mic")]):
        device = namespace[number]
        external = one((n for n in data[kind]
                        if props(n).get("session.audio-group") == group
                        and props(n).get("node.name") == "stream.audio_group:" + group
                        and props(n).get("media.class") == klass), "namespace external " + kind)
        if props(external).get("node.link-group") != props(device)["node.link-group"]:
            raise RouteError("Namespace loopback link groups differ")
        device_owner = owner(data, device, binary="wireplumber")
        external_owner = owner(data, external, binary="wireplumber")
        if ref(device_owner) != ref(external_owner):
            raise RouteError("Namespace device and external stream owners differ")
        target = one((n for n in data[endpoint_kind] if n.get("name") == alvr_name), alvr_name)
        expected_class = "Audio/Sink" if number == 0 else "Audio/Source"
        if (props(target).get("node.name") != alvr_name
                or props(target).get("media.class") != expected_class
                or props(target).get("media.name") != media_name):
            raise RouteError("Unexpected ALVR endpoint class/name")
        target_owner = owner(data, target, server_pid, "vrserver")
        previous = by_index(data, endpoint_kind, external.get(field))
        moves.append({"kind": kind, "field": field, "endpoint_kind": endpoint_kind,
                      "stream": ref(external), "owner": ref(external_owner),
                      "from": ref(previous), "to": ref(target)})
        identities.append({"app": ref(app_nodes[number]), "app_owner": ref(owner(data, app_nodes[number])),
                           "namespace": ref(device), "loopback_owner": ref(device_owner),
                           "alvr_owner": ref(target_owner), "external": ref(external), "alvr": ref(target)})
    return {"app_pid": app_pid, "server_pid": server_pid, "group": group,
            "identities": identities, "moves": moves}


def same_object(node, saved):
    return ref(node) == saved


def checked_stream(data, move):
    stream = by_index(data, move["kind"], move["stream"]["index"])
    if not same_object(stream, move["stream"]):
        raise RouteError("Stream identity changed; refusing reused ID")
    if ref(owner(data, stream, binary="wireplumber")) != move["owner"]:
        raise RouteError("Stream owner identity changed")
    return stream


def checked_endpoint(data, move, saved):
    endpoint = by_index(data, move["endpoint_kind"], saved["index"])
    if not same_object(endpoint, saved):
        raise RouteError("Endpoint identity changed; refusing reused ID")
    return endpoint


def validate_plan(data, plan, completed):
    fresh = discover(data, plan["app_pid"], plan["server_pid"])
    if fresh["group"] != plan["group"] or fresh["identities"] != plan["identities"]:
        raise RouteError("Audio topology/owner identity changed")
    for index, move in enumerate(plan["moves"]):
        stream = checked_stream(data, move)
        wanted = move["to"] if index in completed else move["from"]
        checked_endpoint(data, move, wanted)
        if str(stream[move["field"]]) != str(wanted["index"]):
            raise RouteError("Audio target changed outside transaction")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Journal:
    def __init__(self, path, create=False):
        self.path = Path(path)
        parent = self.path.parent
        parent_stat = parent.lstat()
        if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.getuid() or parent_stat.st_mode & 0o077:
            raise RouteError("Journal parent must be a user-owned private directory (0700)")
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            self.fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise RouteError("Cannot safely open journal: " + str(exc)) from exc
        info = os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            os.close(self.fd)
            raise RouteError("Journal must be an owned, single-link 0600 regular file")
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if create:
                directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except (ImportError, OSError) as exc:
            os.close(self.fd)
            raise RouteError("Cannot lock or sync journal") from exc

    def save(self, value):
        # Append full snapshots so a crash cannot erase the original rollback plan.
        raw = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        os.lseek(self.fd, 0, os.SEEK_END)
        offset = 0
        while offset < len(raw):
            offset += os.write(self.fd, raw[offset:])
        os.fsync(self.fd)

    def read(self):
        os.lseek(self.fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(self.fd), "r") as handle:
            lines = handle.readlines()
        result = None
        for index, line in enumerate(lines):
            if index == len(lines) - 1 and not line.endswith("\n"):
                break
            try:
                value = json.loads(line)
            except (ValueError, TypeError) as exc:
                if index == len(lines) - 1 and not line.endswith("\n"):
                    # A final partial append does not invalidate earlier fsynced records.
                    break
                raise RouteError("Invalid journal JSONL") from exc
            if not isinstance(value, dict):
                raise RouteError("Invalid journal snapshot")
            result = value
        if result is None or result.get("version") != VERSION or not isinstance(result.get("plan", {}).get("moves"), list):
            raise RouteError("Unsupported journal schema")
        # Remove only a crash-truncated tail before appending recovery records.
        complete_bytes = sum(len(line.encode()) for line in lines if line.endswith("\n"))
        if lines and not lines[-1].endswith("\n"):
            os.ftruncate(self.fd, complete_bytes)
            os.fsync(self.fd)
        return result

    def close(self):
        os.close(self.fd)


def record_move(backend, journal, record, move, target, phase):
    attempt = {"time": now(), "phase": phase, "kind": move["kind"],
               "stream": move["stream"], "target": target, "status": "started"}
    record["attempts"].append(attempt)
    journal.save(record)
    try:
        attempt["result"] = backend.move(move["kind"], move["stream"]["index"], target["name"])
        current = snapshot(backend)
        stream = checked_stream(current, move)
        checked_endpoint(current, move, target)
        attempt["verified"] = str(stream[move["field"]]) == str(target["index"])
    except Exception as exc:
        attempt["error"] = str(exc)
        attempt["verified"] = False
    attempt["status"] = "finished"
    journal.save(record)
    return bool(attempt.get("verified")) and attempt.get("result", {}).get("returncode") == 0


def validate_restore_topology(data, plan):
    """Check the saved namespace without requiring live ALVR endpoints."""
    if len(plan["moves"]) != 2 or len(plan.get("identities", [])) != 2:
        raise RouteError("Incomplete namespace identity record")
    for index, move in enumerate(plan["moves"]):
        identity = plan["identities"][index]
        device = by_index(data, move["endpoint_kind"], identity["namespace"]["index"])
        if ref(device) != identity["namespace"]:
            raise RouteError("Namespace device identity changed; manual review required")
        if ref(owner(data, device, binary="wireplumber")) != identity["loopback_owner"]:
            raise RouteError("Namespace device owner changed; manual review required")
        app = by_index(data, move["kind"], identity["app"]["index"])
        if ref(app) != identity["app"] or ref(owner(data, app)) != identity["app_owner"]:
            raise RouteError("Reviewed app stream identity changed; manual review required")
        if str(app.get(move["field"])) != str(device["index"]):
            raise RouteError("Reviewed app left its namespace; manual review required")
        members = [n for n in data[move["kind"]]
                   if str(n.get(move["field"])) == str(device["index"])]
        if len(members) != 1 or ref(members[0]) != identity["app"]:
            raise RouteError("Namespace membership changed; manual review required")
        checked_stream(data, move)


def validate_current_alvr_target(data, plan, move, index):
    """Refuse an ID reused by a replacement target; allow a removed old target."""
    current_targets = [node for node in data[move["endpoint_kind"]]
                       if str(node.get("index")) == str(move["to"]["index"])]
    if not current_targets:
        # PipeWire can briefly retain a removed target's numeric association.
        # The original namespace and its exclusive app membership were checked.
        return
    target = checked_endpoint(data, move, move["to"])
    if ref(owner(data, target, plan["server_pid"], "vrserver")) != plan["identities"][index]["alvr_owner"]:
        raise RouteError("Current ALVR target owner identity changed; leaving stream untouched")


def restore(backend, journal, record, prefix):
    errors = []
    try:
        validate_restore_topology(snapshot(backend), record["plan"])
    except Exception as exc:
        record["rollback_errors"] = [{"kind": "namespace-topology", "error": str(exc), "time": now()}]
        return False
    attempted = {(a["kind"], str(a["stream"]["serial"])) for a in record["attempts"]
                 if a.get("phase") == "apply"}
    for index in reversed(range(len(record["plan"]["moves"]))):
        move = record["plan"]["moves"][index]
        if (move["kind"], str(move["stream"]["serial"])) not in attempted:
            continue
        try:
            data = snapshot(backend)
            validate_restore_topology(data, record["plan"])
            stream = checked_stream(data, move)
            checked_endpoint(data, move, move["from"])
            current = str(stream.get(move["field"]))
            if current == str(move["from"]["index"]):
                continue
            if current != str(move["to"]["index"]):
                raise RouteError("Target changed outside transaction; leaving it untouched")
            validate_current_alvr_target(data, record["plan"], move, index)
            if not record_move(backend, journal, record, move, move["from"], prefix):
                raise RouteError("Restore move failed or readback did not match")
        except Exception as exc:
            errors.append({"kind": move["kind"], "error": str(exc), "time": now()})
    record["rollback_errors"] = errors
    return not errors


def apply(backend, app_pid, server_pid, journal_path):
    plan = discover(snapshot(backend), app_pid, server_pid)
    if all(move["from"] == move["to"] for move in plan["moves"]):
        raise RouteError("Namespace is already routed; no new transaction needed")
    journal = Journal(journal_path, create=True)
    record = {"version": VERSION, "created": now(), "status": "prepared", "plan": plan, "attempts": []}
    try:
        journal.save(record)
        completed = set()
        try:
            for index, move in enumerate(plan["moves"]):
                validate_plan(snapshot(backend), plan, completed)
                if move["from"] != move["to"]:
                    if not record_move(backend, journal, record, move, move["to"], "apply"):
                        raise RouteError("Move failed or target readback did not match")
                completed.add(index)
            validate_plan(snapshot(backend), plan, completed)
            record["status"] = "applied"
        except Exception as exc:
            record["apply_error"] = str(exc)
            record["status"] = "apply_failed_rolled_back" if restore(backend, journal, record, "compensate") else "apply_failed_rollback_incomplete"
        record["finished"] = now()
        journal.save(record)
        return record
    finally:
        journal.close()


def rollback(backend, journal_path):
    journal = Journal(journal_path)
    try:
        record = journal.read()
        record["status"] = "rolling_back"
        journal.save(record)
        record["status"] = "rolled_back" if restore(backend, journal, record, "rollback") else "rollback_incomplete"
        record["rollback_finished"] = now()
        journal.save(record)
        return record
    finally:
        journal.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply", "rollback"])
    parser.add_argument("--app-pid", type=int)
    parser.add_argument("--vrserver-pid", type=int)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Live CLI requires Linux native pactl; use mocked unit tests on other hosts")
    if os.getuid() == 0:
        parser.error("Run as the desktop audio session user, not UID0")
    if args.action in ("plan", "apply") and (not args.app_pid or not args.vrserver_pid):
        parser.error("plan/apply require reviewed --app-pid and --vrserver-pid")
    if args.action != "plan" and args.journal is None:
        parser.error("apply/rollback require --journal")
    backend = Pactl()
    try:
        if args.action == "plan":
            result = discover(snapshot(backend), args.app_pid, args.vrserver_pid)
        elif args.action == "apply":
            result = apply(backend, args.app_pid, args.vrserver_pid, args.journal)
        else:
            result = rollback(backend, args.journal)
        print(json.dumps(result, indent=2))
        return 0 if args.action == "plan" or result["status"] in ("applied", "rolled_back") else 1
    except (RouteError, OSError, ValueError, KeyError, TypeError) as exc:
        print("Audio routing refused: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
