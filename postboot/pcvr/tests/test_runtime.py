"""Host fixture checks for portable wrappers, profiles, payloads, and retry receipts."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "runtime"))
import steamvr_runtime_escape as outer
import steamvr_inner_runtime as inner
import retry_gate
from alvr_profile_request import request
spec = importlib.util.spec_from_file_location("render_profiles", HERE / "profiles/render_profiles.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)

class RuntimeTests(unittest.TestCase):
    def test_wrapper_preserves_guest_path_and_chain(self):
        steam = Path("/fixture/home/.local/share/Steam")
        with patch.dict(os.environ, {"CAIHONG_HOME": "/fixture/home"}, clear=False), patch.object(Path, "is_dir", return_value=True):
            args = [str(steam / "linuxarm64/steam-launch-wrapper"), "--", str(steam / "steamapps/common/FEX-Emu/fex-compat-tool"), str(steam / "steamapps/common/SteamVR/bin/vrstartup.sh")]
            env = {"SteamAppId": "250820", "LD_LIBRARY_PATH": "/guest/scout"}
            result, changed = outer.prepare(args, dict(env))
            self.assertEqual(changed["LD_LIBRARY_PATH"], "/guest/scout")
            self.assertEqual(result[:3], args[:3])
            self.assertEqual(result[-1], args[-1])
            self.assertIn("steamvr_inner_runtime.py", result[-2])
            self.assertIn("/usr/lib64", changed["SYSTEM_LD_LIBRARY_PATH"])
            with self.assertRaises(ValueError):
                outer.prepare(args, {"SteamAppId": "438100"})

    def test_ipc_directory_recreated_and_rejects_unsafe_state(self):
        import install_profiles
        from types import SimpleNamespace
        import stat
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            uid = os.getuid()
            path = install_profiles.secure_ipc_dir(uid, base)
            self.assertEqual(path, base / ("caihong-alvr-" + str(uid)))
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            path.rmdir()
            self.assertEqual(install_profiles.secure_ipc_dir(uid, base), path)
            path.chmod(0o755)
            with self.assertRaises(ValueError):
                install_profiles.secure_ipc_dir(uid, base)
            path.chmod(0o700)
            fake = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=uid + 1)
            with patch.object(Path, "lstat", return_value=fake), self.assertRaises(ValueError):
                install_profiles.secure_ipc_dir(uid, base)
            path.rmdir()
            target = base / "target"
            target.mkdir(mode=0o700)
            path.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                install_profiles.secure_ipc_dir(uid, base)

    def test_runtime_recreates_ipc_before_receipt_consumption(self):
        events = []
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            with patch.object(outer, "prepare", return_value=(["/fixture/launch"], {})), \
                 patch.object(outer, "secure_ipc_dir", side_effect=lambda uid: events.append("ipc")), \
                 patch.object(outer, "consume_receipt", side_effect=lambda: events.append("receipt")), \
                 patch.object(outer, "state_root", return_value=state), \
                 patch.object(outer.os, "execve", side_effect=lambda *args: events.append("exec")):
                outer.main()
            self.assertEqual(events, ["ipc", "receipt", "exec"])
            with patch.object(outer, "prepare", return_value=(["/fixture/launch"], {})), \
                 patch.object(outer, "secure_ipc_dir", side_effect=ValueError("unsafe IPC dir")), \
                 patch.object(outer, "consume_receipt") as consume, self.assertRaises(ValueError):
                outer.main()
            consume.assert_not_called()

    def test_inner_requires_valve_runtime(self):
        with patch.dict(os.environ, {"CAIHONG_HOME": "/fixture/home"}, clear=False):
            args = ["/fixture/home/.local/share/Steam/steamapps/common/SteamVR/bin/vrstartup.sh"]
            with self.assertRaises(ValueError):
                inner.prepare(args, {"SteamAppId": "250820"})
            result, env = inner.prepare(args, {"SteamAppId": "250820", "PRESSURE_VESSEL_RUNTIME": "/runtime", "LD_LIBRARY_PATH": "/guest"})
            self.assertEqual(result, args)
            self.assertEqual(env["LD_LIBRARY_PATH"], "/guest")

    def test_profiles_keep_repeated_keys(self):
        data = renderer.render("/fixture/home", 1234, "gamescope-7")
        comp = data["vrcompositor.real.json"]
        self.assertEqual(comp.count('"HostEnv"'), 2)
        self.assertEqual(comp.count('"Env"'), 5)
        self.assertIn("GAMESCOPE_WAYLAND_DISPLAY=/run/user/1234/gamescope-7", comp)
        self.assertIn("XDG_RUNTIME_DIR=/tmp/caihong-alvr-1234", comp)
        pairs = json.loads(comp, object_pairs_hook=list)
        config = pairs[0][1]
        self.assertEqual(sum(key == "HostEnv" for key, value in config), 2)
        server = data["server-fex-config.json"]
        self.assertEqual(server.count('"HostEnv"'), 2)
        self.assertIn('"vrserver"', server)
        self.assertIn('"vrmonitor"', server)
        monitor = data["vrmonitor.json"]
        self.assertEqual(monitor.count('"HostEnv"'), 1)
        self.assertIn("/bin/linux64/qt/lib:/usr/lib", monitor)
        self.assertNotIn("XDG_RUNTIME_DIR", monitor)

    def test_settings_payload_rejects_missing_keys_and_wrong_types(self):
        profile = {"values": {"session_settings.connection.max_queued_server_video_frames": 1}}
        session = {"session_settings": {"connection": {"max_queued_server_video_frames": 2}}}
        self.assertEqual(request(profile, session)["SetValues"][0]["value"], 1)
        with self.assertRaises(ValueError):
            request(profile, {})
        with self.assertRaises(ValueError):
            request({"values": {"session_settings.connection.max_queued_server_video_frames": 1.0}}, session)

    def test_retry_gate_backups_and_single_consumption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "steamvr.vrsettings"
            settings.write_text(json.dumps({"driver_alvr_server": {"blocked_by_safe_mode": True}, "steamvr": {"disableLinuxWaitForPresent": True}}))
            marker = root / "vrserver_crash_timestamp.txt"
            marker.write_text("1 2 3\n")
            review = root / "review.md"
            review.write_text("Reviewed fixture fault; one correction.")
            state = root / "state"
            with self.assertRaises(ValueError):
                retry_gate.prepare_retry(settings, state, fault_reviewed=False, evidence_path=review)
            receipt = retry_gate.prepare_retry(settings, state, fault_reviewed=True, evidence_path=review)
            self.assertTrue((Path(receipt["backup"]) / marker.name).exists())
            self.assertFalse(marker.exists())
            self.assertFalse(json.loads(settings.read_text())["driver_alvr_server"]["blocked_by_safe_mode"])
            self.assertTrue(json.loads(settings.read_text())["steamvr"]["disableLinuxWaitForPresent"])
            with patch.object(retry_gate, "check_closed"):
                retry_gate.consume_receipt(state)
                with self.assertRaises(RuntimeError):
                    retry_gate.consume_receipt(state)

    def test_process_gate_ignores_wrapper_arguments_not_real_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            cases = [("900001", "steam-reaper", ["steam-reaper", "/example/vrstartup.sh"]),
                     ("900002", "vrcompositor.re", ["FEX", "/example/vrcompositor.real"]),
                     ("900003", "FEXInterpreter", ["FEXInterpreter", "/example/vrserver"])]
            for pid, comm, argv in cases:
                directory = proc / pid
                directory.mkdir()
                (directory / "comm").write_text(comm)
                (directory / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv))
            self.assertEqual(retry_gate.active_processes(proc), [900002, 900003])

    def test_retry_gate_rejects_expired_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "retry-receipt.json").write_text(json.dumps({"created_at": 1, "appid": 250820, "attempts": 1}))
            with self.assertRaises(RuntimeError):
                retry_gate.consume_receipt(root, now=1000)

if __name__ == "__main__":
    unittest.main()
