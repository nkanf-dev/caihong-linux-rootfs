"""Host-only tests. Fake runtime; no Steam, network, or device commands."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import dual_mode as dm

class FakeRuntime:
    def __init__(self, states):
        self.states = list(states)
        self.clock = 0.0
        self.calls = []
    def inspect(self):
        self.calls.append("inspect")
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]
    def prepare(self): self.calls.append("prepare")
    def start(self): self.calls.append("start")
    def wait(self, seconds):
        self.calls.append("wait")
        self.clock += seconds
    def monotonic(self): return self.clock
    def record(self, event, **fields): self.calls.append(event)

READY = dm.Snapshot(processes=((11, "vrserver", 1), (12, "vrcompositor", 2), (13, "vrmonitor", 3)),
                    driver_loaded=True, monitor_ready=True, fresh_stream=True, receipt_consumed=True)
CLOSED = dm.Snapshot()

class DualModeTests(unittest.TestCase):
    def test_real_steam_choices(self):
        fixture = json.loads((HERE / "steam-launch-choices.json").read_text())
        self.assertNotIn("arguments", fixture["launch"]["0"])
        self.assertEqual(fixture["launch"]["1"]["arguments"], "--no-vr")
        self.assertEqual(dm.select_mode(["launch.exe"]), "vr")
        self.assertEqual(dm.select_mode(["launch.exe", "--no-vr"]), "desktop")
        self.assertEqual(dm.select_mode(["launch.exe"], "desktop"), "desktop")
        for args, mode in [(["--no-vr", "--vr"], "auto"), (["--no-vr"], "vr"),
                           (["--no-vr", "--no-vr"], "auto"), (["--no-vr=true"], "auto")]:
            with self.subTest(args=args, mode=mode), self.assertRaises(dm.LaunchError):
                dm.select_mode(args, mode)

    def test_desktop_forwards_exactly_once_without_runtime(self):
        args = ["/original/tool", "a space", "launch.exe", "--no-vr", "--account=not-logged"]
        backend = Mock(side_effect=AssertionError("desktop touched runtime"))
        execute = Mock()
        dm.dispatch(args, {"sentinel":"unchanged"}, "auto", backend, execute, validate=lambda *a: None)
        backend.assert_not_called()
        execute.assert_called_once_with(args, {"sentinel":"unchanged"})

    def test_forced_desktop_adds_no_vr_once(self):
        execute = Mock()
        dm.dispatch(["launch.exe"], {}, "desktop", Mock(), execute, validate=lambda *a: None)
        execute.assert_called_once_with(["launch.exe", "--no-vr"], {})

    def test_guard_runs_before_runtime_and_failure_does_not_exec(self):
        backend, execute = Mock(), Mock()
        def guard(*args): raise dm.LaunchError("wrong prefix")
        with self.assertRaises(dm.LaunchError):
            dm.dispatch(["launch.exe"], {}, "auto", backend, execute, validate=guard)
        backend.assert_not_called()
        execute.assert_not_called()

    def test_ready_reuse_does_not_prepare_or_launch(self):
        runtime = FakeRuntime([READY])
        self.assertEqual(dm.ensure_vr(runtime, timeout=3), "reused")
        self.assertNotIn("prepare", runtime.calls)
        self.assertNotIn("start", runtime.calls)

    def test_cold_start_once_then_ready(self):
        runtime = FakeRuntime([CLOSED, replace(READY, fresh_stream=False), READY])
        self.assertEqual(dm.ensure_vr(runtime, timeout=3), "started")
        self.assertEqual(runtime.calls.count("prepare"), 1)
        self.assertEqual(runtime.calls.count("start"), 1)
        self.assertIn("wait", runtime.calls)

    def test_timeout_has_one_start_no_exec_and_no_restart(self):
        runtime = FakeRuntime([CLOSED])
        with self.assertRaisesRegex(dm.LaunchError, "deadline"):
            dm.ensure_vr(runtime, timeout=2)
        self.assertEqual(runtime.calls.count("start"), 1)
        self.assertLessEqual(runtime.clock, 2)
        self.assertIn("failed", runtime.calls)

    def test_runtime_start_failure_has_no_second_attempt(self):
        runtime = FakeRuntime([CLOSED])
        runtime.start = Mock(side_effect=dm.LaunchError("request failed"))
        with self.assertRaises(dm.LaunchError): dm.ensure_vr(runtime, timeout=2)
        runtime.start.assert_called_once()

    def test_unsafe_states_fail_without_start_or_prepare(self):
        cases = [replace(CLOSED, crash_marker=True), replace(CLOSED, alvr_blocked=True),
                 replace(CLOSED, trusted_client=False), replace(CLOSED, collision=True),
                 replace(READY, collision=True)]
        for state in cases:
            with self.subTest(state=state):
                runtime = FakeRuntime([state])
                with self.assertRaises(dm.LaunchError): dm.ensure_vr(runtime, timeout=2)
                self.assertNotIn("start", runtime.calls)
                self.assertNotIn("prepare", runtime.calls)

    def test_live_but_unhealthy_runtime_not_restarted(self):
        runtime = FakeRuntime([replace(READY, fresh_stream=False)])
        with self.assertRaisesRegex(dm.LaunchError, "headset"):
            dm.ensure_vr(runtime, timeout=1)
        self.assertNotIn("start", runtime.calls)

    def test_runtime_pid_changed_fails_instead_of_accepting_new_run(self):
        runtime = FakeRuntime([replace(READY, fresh_stream=False),
                               replace(READY, processes=((99,"vrserver",9),))])
        with self.assertRaisesRegex(dm.LaunchError, "changed"):
            dm.ensure_vr(runtime, timeout=3)
        self.assertNotIn("start", runtime.calls)

    def test_game_not_launched_until_receipt_consumed(self):
        runtime = FakeRuntime([CLOSED, replace(READY, receipt_consumed=False)])
        with self.assertRaises(dm.LaunchError): dm.ensure_vr(runtime, timeout=1)
        self.assertEqual(runtime.calls.count("start"), 1)

    def test_steam_started_first_waits_without_second_uri(self):
        runtime = FakeRuntime([replace(CLOSED, starting=True), READY])
        self.assertEqual(dm.ensure_vr(runtime, timeout=2), "reused")
        self.assertNotIn("prepare", runtime.calls)
        self.assertNotIn("start", runtime.calls)

    def test_steam_wins_prepare_race_no_second_uri(self):
        runtime = FakeRuntime([CLOSED, READY])
        runtime.prepare = lambda: False
        self.assertEqual(dm.ensure_vr(runtime, timeout=2), "reused")
        self.assertNotIn("start", runtime.calls)

    def test_guard_prefix_tool_and_eac_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            prefix = home / ".local/share/cvrc-x64"
            private = home / ".local/share/caihong-vrchat-fex-eac-tool"
            prefix.mkdir(parents=True)
            private.mkdir()
            stock = home / ".local/share/Steam/steamapps/common/FEX-Emu/fex-compat-tool"
            stock.parent.mkdir(parents=True)
            tool = private / "fex-compat-tool"
            for p in [stock, tool]:
                p.write_text("#!/bin/true\n")
                p.chmod(0o700)
            args = [str(stock), "proton", "waitforexitandrun", "/game/launch.exe"]
            env = {"SteamAppId":"438100", "STEAM_COMPAT_DATA_PATH":str(prefix)}
            dm.validate_command(args, env, home=home)
            for bad_args, bad_env in [(args+ [str(stock)], env), (args, dict(env, SteamAppId="250820")),
                  (args,dict(env, STEAM_COMPAT_DATA_PATH="/shared")),
                  (args,dict(env, FEX_HIDEHYPERVISORBIT="1")),
                  (args[:-1]+["/game/VRChat.exe"],env)]:
                with self.subTest(args=bad_args), self.assertRaises(dm.LaunchError):
                    dm.validate_command(bad_args,bad_env,home=home)
            tool.chmod(0o777)
            with self.assertRaises(dm.LaunchError): dm.validate_command(args, env, home=home)

    def test_child_steam_env_does_not_leak_game_overrides(self):
        source = {"SteamAppId":"438100", "SteamGameId":"438100", "STEAM_COMPAT_DATA_PATH":"/private",
                  "FEX_APP_CONFIG":"/game", "VK_DRIVER_FILES":"/game.json", "PROTON_LOG":"1",
                  "LD_LIBRARY_PATH":"/guest", "DISPLAY":":0", "PATH":"/usr/bin", "XDG_RUNTIME_DIR":"/run/user/1"}
        result = dm.steam_environment(source)
        self.assertEqual(result["DISPLAY"], ":0")
        self.assertEqual(result["XDG_RUNTIME_DIR"], "/run/user/1")
        for key in source.keys() - {"DISPLAY", "PATH", "XDG_RUNTIME_DIR"}:
            self.assertNotIn(key, result)
        self.assertEqual(source["SteamAppId"], "438100")

if __name__ == "__main__": unittest.main()
