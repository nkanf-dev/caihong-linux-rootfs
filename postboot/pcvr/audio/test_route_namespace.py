"""Host-only tests. Every pactl response and move is mocked."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).with_name("route_namespace.py")
spec = importlib.util.spec_from_file_location("route_namespace", MODULE)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def fixture(offset=0):
    group = "pw-audio-namespace.700"
    def client(index, oid, binary, pid, name=None):
        return {"index": index + offset, "properties": {
            "object.id": str(oid + offset), "object.serial": str(index + offset),
            "application.process.binary": binary, "application.process.id": str(pid),
            "application.name": name or binary, "pipewire.sec.pid": str(pid)}}
    def node(index, name, klass, cid, **props):
        p = {"object.id": str(index + offset), "object.serial": str(index + offset),
             "node.name": name, "media.class": klass, "client.id": str(cid + offset)}
        p.update(props)
        return {"index": index + offset, "name": name, "properties": p}
    ns = "device.audio_group:" + group
    ext = "stream.audio_group:" + group
    sinks = [node(47, "tablet-speaker", "Audio/Sink", 33),
             node(1780, "ALVR Audio", "Audio/Sink", 87, **{"media.name": "alvr-audio"}),
             node(1918, ns, "Audio/Sink", 130, **{"session.audio-group": group, "node.link-group": "out-group"})]
    sources = [node(48, "tablet-mic", "Audio/Source", 33),
               node(1779, "ALVR Microphone", "Audio/Source", 103, **{"media.name": "alvr-mic"}),
               node(1937, ns, "Audio/Source", 109, **{"session.audio-group": group, "node.link-group": "in-group"})]
    out = node(1915, "VRChat.exe", "Stream/Output/Audio", 80,
               **{"application.name": "VRChat.exe", "application.process.id": "900"})
    out["sink"] = 1918 + offset
    extout = node(1917, ext, "Stream/Output/Audio", 130,
                  **{"session.audio-group": group, "node.link-group": "out-group"})
    extout["sink"] = 47 + offset
    mic = node(1968, "VRChat.exe", "Stream/Input/Audio", 80,
               **{"application.name": "VRChat.exe", "application.process.id": "900"})
    mic["source"] = 1937 + offset
    extmic = node(1938, ext, "Stream/Input/Audio", 109,
                  **{"session.audio-group": group, "node.link-group": "in-group"})
    extmic["source"] = 48 + offset
    return {"sinks": sinks, "sources": sources, "sink-inputs": [out, extout],
            "source-outputs": [mic, extmic], "clients": [
                client(33, 33, "wireplumber", 100),
                client(1778, 87, "vrserver", 800), client(1777, 103, "vrserver", 800),
                client(1914, 80, "wine64-preloader", 900, "VRChat.exe"),
                client(1916, 130, "wireplumber", 100), client(1936, 109, "wireplumber", 100)]}


class FakePactl:
    def __init__(self, data=None, fail_move=None):
        self.data = data or fixture()
        self.moves = []
        self.fail_move = fail_move
        self.before_move = None
        self.after_move = None

    def list(self, kind):
        return copy.deepcopy(self.data[kind])

    def move(self, kind, index, target):
        if self.before_move:
            self.before_move(kind, index, target)
        self.moves.append((kind, index, target))
        if self.fail_move == len(self.moves):
            return {"returncode": 1, "stdout": "", "stderr": "synthetic failure"}
        target_kind = "sinks" if kind == "sink-inputs" else "sources"
        field = "sink" if kind == "sink-inputs" else "source"
        endpoint = next(n for n in self.data[target_kind] if n["name"] == target)
        stream = next(n for n in self.data[kind] if n["index"] == index)
        stream[field] = endpoint["index"]
        if self.after_move:
            self.after_move(kind, index, target)
        return {"returncode": 0, "stdout": "", "stderr": ""}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.directory.chmod(0o700)
        self.path = self.directory / "transaction.json"
        self.backend = FakePactl()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return route.discover(route.snapshot(self.backend), 900, 800)

    def test_discovery_uses_namespace_external_streams_and_owner_object_ids(self):
        plan = self.plan()
        self.assertEqual([m["stream"]["index"] for m in plan["moves"]], [1917, 1938])
        self.assertEqual([m["to"]["name"] for m in plan["moves"]], ["ALVR Audio", "ALVR Microphone"])
        self.assertEqual([m["from"]["name"] for m in plan["moves"]], ["tablet-speaker", "tablet-mic"])
        self.assertFalse(self.backend.moves)

    def test_dynamic_ids(self):
        self.backend.data = fixture(10000)
        self.assertEqual(self.plan()["moves"][0]["stream"]["index"], 11917)

    def test_missing_alvr_endpoint_is_noop(self):
        self.backend.data["sinks"] = self.backend.data["sinks"][:1] + self.backend.data["sinks"][2:]
        with self.assertRaises(route.RouteError):
            route.apply(self.backend, 900, 800, self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.backend.moves)

    def test_duplicate_endpoint_rejected(self):
        self.backend.data["sources"].append(copy.deepcopy(self.backend.data["sources"][1]))
        with self.assertRaises(route.RouteError): self.plan()

    def test_wrong_alvr_owner_rejected(self):
        self.backend.data["clients"][1]["properties"]["application.process.id"] = "999"
        with self.assertRaises(route.RouteError): self.plan()

    def test_wrong_alvr_security_pid_rejected(self):
        self.backend.data["clients"][1]["properties"]["pipewire.sec.pid"] = "999"
        with self.assertRaises(route.RouteError): self.plan()

    def test_pulse_app_security_pid_belongs_to_pulse_daemon(self):
        client = self.backend.data["clients"][3]["properties"]
        client["client.api"] = "pipewire-pulse"
        client["pipewire.sec.pid"] = "2081"
        self.assertEqual(self.plan()["app_pid"], 900)

    def test_namespace_mismatch_rejected(self):
        self.backend.data["sources"][2]["properties"]["session.audio-group"] = "pw-audio-namespace.701"
        with self.assertRaises(route.RouteError): self.plan()

    def test_loopback_link_group_mismatch_rejected(self):
        self.backend.data["sink-inputs"][1]["properties"]["node.link-group"] = "wrong"
        with self.assertRaises(route.RouteError): self.plan()

    def test_other_app_namespace_member_rejected(self):
        other = copy.deepcopy(self.backend.data["sink-inputs"][0])
        other["index"] = 9999
        other["properties"]["application.name"] = "Other.exe"
        other["properties"]["application.process.id"] = "901"
        self.backend.data["sink-inputs"].append(other)
        with self.assertRaises(route.RouteError): self.plan()

    def test_journal_is_saved_private_before_first_write(self):
        def check(*args):
            saved = json.loads(self.path.read_text().splitlines()[-1])
            self.assertEqual(saved["plan"]["moves"][0]["from"]["name"], "tablet-speaker")
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(saved["attempts"][-1]["status"], "started")
        self.backend.before_move = check
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.backend.data["sink-inputs"][0]["sink"], 1918)
        self.assertEqual(self.backend.data["source-outputs"][0]["source"], 1937)
        self.assertEqual(len(self.backend.moves), 2)

    def test_second_move_failure_restores_first_and_records_results(self):
        self.backend.fail_move = 2
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rolled_back")
        self.assertEqual(self.backend.moves[-1], ("sink-inputs", 1917, "tablet-speaker"))
        self.assertEqual(self.backend.data["sink-inputs"][1]["sink"], 47)
        self.assertEqual(result["attempts"][1]["result"]["returncode"], 1)
        self.assertTrue(result["attempts"][0]["verified"])

    def test_first_move_failure_no_second_write(self):
        self.backend.fail_move = 1
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rolled_back")
        self.assertEqual(len(self.backend.moves), 1)

    def test_existing_journal_is_not_overwritten(self):
        self.path.write_text("keep")
        with self.assertRaises(route.RouteError): route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(self.path.read_text(), "keep")
        self.assertFalse(self.backend.moves)

    def test_symlink_journal_rejected(self):
        other = self.directory / "other"
        other.write_text("keep")
        self.path.symlink_to(other)
        with self.assertRaises(route.RouteError): route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(other.read_text(), "keep")
        self.assertFalse(self.backend.moves)

    def test_rollback_restores_both_only_if_identities_match(self):
        route.apply(self.backend, 900, 800, self.path)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(self.backend.moves[-2:], [("source-outputs", 1938, "tablet-mic"), ("sink-inputs", 1917, "tablet-speaker")])
        self.assertEqual(self.backend.data["source-outputs"][1]["source"], 48)

    def test_rollback_refuses_reused_stream_serial(self):
        route.apply(self.backend, 900, 800, self.path)
        self.backend.data["sink-inputs"][1]["properties"]["object.serial"] = "99999"
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertFalse(any(m[0] == "sink-inputs" for m in self.backend.moves[count:]))

    def test_rollback_accepts_original_target_after_disconnect_fallback(self):
        route.apply(self.backend, 900, 800, self.path)
        self.backend.data["sinks"].pop(1)
        self.backend.data["sources"].pop(1)
        self.backend.data["sink-inputs"][1]["sink"] = 47
        self.backend.data["source-outputs"][1]["source"] = 48
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(len(self.backend.moves), count)

    def test_rollback_restores_if_old_alvr_endpoint_is_genuinely_absent(self):
        route.apply(self.backend, 900, 800, self.path)
        self.backend.data["sinks"].pop(1)
        self.backend.data["sources"].pop(1)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(self.backend.moves[-2:], [("source-outputs", 1938, "tablet-mic"),
                                                  ("sink-inputs", 1917, "tablet-speaker")])

    def test_rollback_refuses_reused_current_alvr_target_id(self):
        route.apply(self.backend, 900, 800, self.path)
        for kind in ("sinks", "sources"):
            replacement = self.backend.data[kind][1]
            replacement["name"] = "unrelated-replacement"
            replacement["properties"]["node.name"] = "unrelated-replacement"
            replacement["properties"]["object.serial"] = "99999"
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertEqual(len(self.backend.moves), count)

    def test_rollback_refuses_replaced_current_alvr_owner(self):
        route.apply(self.backend, 900, 800, self.path)
        for client_index in (1, 2):
            self.backend.data["clients"][client_index]["properties"]["application.process.id"] = "999"
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertEqual(len(self.backend.moves), count)

    def test_rollback_refuses_new_output_namespace_member(self):
        route.apply(self.backend, 900, 800, self.path)
        other = copy.deepcopy(self.backend.data["sink-inputs"][0])
        other["index"] = 9999
        other["properties"]["object.id"] = "9999"
        other["properties"]["object.serial"] = "9999"
        other["properties"]["application.name"] = "Other.exe"
        other["properties"]["application.process.id"] = "901"
        self.backend.data["sink-inputs"].append(other)
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertEqual(len(self.backend.moves), count)

    def test_rollback_refuses_new_capture_namespace_member(self):
        route.apply(self.backend, 900, 800, self.path)
        other = copy.deepcopy(self.backend.data["source-outputs"][0])
        other["index"] = 9998
        other["properties"]["object.id"] = "9998"
        other["properties"]["object.serial"] = "9998"
        other["properties"]["application.name"] = "Other.exe"
        other["properties"]["application.process.id"] = "901"
        self.backend.data["source-outputs"].append(other)
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertEqual(len(self.backend.moves), count)

    def test_rollback_refuses_changed_loopback_owner_pid(self):
        route.apply(self.backend, 900, 800, self.path)
        self.backend.data["clients"][4]["properties"]["application.process.id"] = "555"
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertFalse(any(m[0] == "sink-inputs" for m in self.backend.moves[count:]))

    def test_truncated_journal_tail_keeps_original_plan_for_recovery(self):
        route.apply(self.backend, 900, 800, self.path)
        with self.path.open("a") as handle:
            handle.write('{"unfinished":')
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rolled_back")
        self.assertTrue(all(isinstance(json.loads(line), dict) for line in self.path.read_text().splitlines()))

    def test_uncertain_failed_second_move_is_also_restored(self):
        original_move = self.backend.move
        def uncertain(kind, index, target):
            result = original_move(kind, index, target)
            if len(self.backend.moves) == 2:
                return {"returncode": 1, "stdout": "", "stderr": "reply lost after move"}
            return result
        self.backend.move = uncertain
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rolled_back")
        self.assertEqual(self.backend.data["sink-inputs"][1]["sink"], 47)
        self.assertEqual(self.backend.data["source-outputs"][1]["source"], 48)

    def test_rollback_does_not_override_later_third_party_route(self):
        route.apply(self.backend, 900, 800, self.path)
        self.backend.data["sink-inputs"][1]["sink"] = 12345
        count = len(self.backend.moves)
        result = route.rollback(self.backend, self.path)
        self.assertEqual(result["status"], "rollback_incomplete")
        self.assertFalse(any(m[0] == "sink-inputs" for m in self.backend.moves[count:]))

    def test_second_compensation_failure_is_recorded(self):
        original_move = self.backend.move
        def fail(kind, index, target):
            if len(self.backend.moves) in (1, 2):
                self.backend.moves.append((kind, index, target))
                return {"returncode": 1, "stdout": "", "stderr": "synthetic compensation failure"}
            return original_move(kind, index, target)
        self.backend.move = fail
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rollback_incomplete")
        self.assertTrue(result["rollback_errors"])
        self.assertEqual(result["attempts"][-1]["result"]["returncode"], 1)

    def test_alvr_disappears_before_second_move_no_replacement_created(self):
        def disappear(*args):
            if len(self.backend.moves) == 1:
                self.backend.data["sources"].pop(1)
        self.backend.after_move = disappear
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rolled_back")
        self.assertEqual(self.backend.moves, [("sink-inputs", 1917, "ALVR Audio"),
                                             ("sink-inputs", 1917, "tablet-speaker")])

    def test_nonprivate_journal_parent_rejected_before_writes(self):
        self.directory.chmod(0o755)
        with self.assertRaises(route.RouteError): route.apply(self.backend, 900, 800, self.path)
        self.assertFalse(self.backend.moves)

    def test_revalidation_stops_changed_group_before_second_move(self):
        def change(*args):
            if len(self.backend.moves) == 1:
                self.backend.data["sources"][2]["properties"]["session.audio-group"] = "pw-audio-namespace.999"
        self.backend.after_move = change
        result = route.apply(self.backend, 900, 800, self.path)
        self.assertEqual(result["status"], "apply_failed_rollback_incomplete")
        self.assertEqual(self.backend.moves, [("sink-inputs", 1917, "ALVR Audio")])
        self.assertEqual(result["rollback_errors"][0]["kind"], "namespace-topology")


if __name__ == "__main__":
    unittest.main()
