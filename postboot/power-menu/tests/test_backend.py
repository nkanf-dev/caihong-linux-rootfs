# SPDX-License-Identifier: MIT
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location("power_backend", Path(__file__).parents[1] / "main.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CONFIG = {"schema": 1, "approved": True, "android_slot": "a", "linux_slot": "b",
          "slot_script_sha256": "a" * 64, "qbootctl_sha256": "b" * 64}


class MockSystem:
    def __init__(self):
        self.calls = []
        self.active = "b"
        self.current = "b"
        self.bootable = True
        self.successful = True
        self.inhibitors = []
        self.allow = "yes"
        self.state = "running"
        self.preparing = False
        self.scheduled = ["", 0]
        self.fail = None
        self.skip_select = False
        self.firmware = False
        self.bootmenu = 18446744073709551615
        self.bootentry = ""
        self.post_inhibitor = False

    async def run(self, *args):
        self.calls.append(args)
        if self.fail == args:
            raise m.SafetyError("mock failure")
        if args == (m.QBOOT, "-c"):
            return f"Current slot: _{self.current}"
        if args == (m.QBOOT, "-a"):
            return f"Active slot: _{self.active}"
        if args == (m.QBOOT, "-b", "a"):
            return f"SLOT _a: is {'' if self.bootable else 'not '}marked bootable"
        if args == (m.QBOOT, "-n", "a"):
            return f"SLOT _a: is {'' if self.successful else 'not '}marked successful"
        if args == (m.SLOT, "android"):
            if not self.skip_select:
                self.active = "a"
            if self.post_inhibitor:
                self.inhibitors = [["shutdown", "game", "save", "delay", 1000, 9]]
            return "Next boot: Android (_a)"
        if args == (m.SYSTEMCTL, "--check-inhibitors=yes", "is-system-running"):
            return self.state
        if args == (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot"):
            return ""
        if args[0] == m.BUS:
            if args[-1] == "CanReboot":
                return json.dumps({"type": "s", "data": [self.allow]})
            if args[-1] == "ListInhibitors":
                return json.dumps({"type": "a(ssssuu)", "data": [self.inhibitors]})
            if args[-1] == "PreparingForShutdown":
                return json.dumps({"type": "b", "data": [self.preparing]})
            if args[-1] == "ScheduledShutdown":
                return json.dumps({"type": "(st)", "data": [self.scheduled]})
            if args[-1] == "RebootToFirmwareSetup":
                return json.dumps({"type": "b", "data": [self.firmware]})
            if args[-1] == "RebootToBootLoaderMenu":
                return json.dumps({"type": "t", "data": [self.bootmenu]})
            if args[-1] == "RebootToBootLoaderEntry":
                return json.dumps({"type": "s", "data": [self.bootentry]})
        raise AssertionError(f"Unexpected command {args!r}")

    def writes(self):
        return [x for x in self.calls if x[0] == m.SLOT or x[-1] == "reboot"]


class BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.system = MockSystem()
        self.patches = [patch.object(m, "run_command", self.system.run),
                        patch.object(m, "deployment", return_value=CONFIG.copy()),
                        patch.object(m, "trusted_file", return_value=b"trusted"),
                        patch.object(m.os, "access", return_value=True),
                        patch.dict(m.os.environ, {"SERVER_HOST": "127.0.0.1"}),
                        patch.object(m.sys, "platform", "linux"),
                        patch.object(m.os, "geteuid", return_value=0)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.plugin = m.Plugin()

    async def test_load_unload_run_no_commands(self):
        await self.plugin._main()
        await self.plugin._unload()
        self.assertEqual(self.system.calls, [])

    async def test_prepare_cancel_never_write(self):
        prepared = await self.plugin.prepare_return()
        self.assertEqual(prepared["expires_in"], 45)
        await self.plugin.cancel_return(prepared["token"])
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.writes(), [])

    async def test_expired_and_missing_confirmation_never_write(self):
        for token in [None, "unknown"]:
            with self.assertRaises(m.SafetyError):
                await self.plugin.confirm_return(token)
        prepared = await self.plugin.prepare_return()
        self.plugin._pending = (prepared["token"], time.monotonic() - 1)
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.writes(), [])

    async def test_wrong_token_consumes_confirmation(self):
        prepared = await self.plugin.prepare_return()
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return("wrong")
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.writes(), [])

    async def test_one_confirmation_one_supported_script_and_normal_reboot(self):
        prepared = await self.plugin.prepare_return()
        self.assertEqual(await self.plugin.confirm_return(prepared["token"]), {"reboot_requested": True})
        self.assertEqual(self.system.writes(), [(m.SLOT, "android"), (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot")])
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(len(self.system.writes()), 2)
        select = self.system.calls.index((m.SLOT, "android"))
        reboot = self.system.calls.index((m.SYSTEMCTL, "--check-inhibitors=yes", "reboot"))
        self.assertIn((m.QBOOT, "-a"), self.system.calls[select + 1:reboot])
        self.assertIn((m.SYSTEMCTL, "--check-inhibitors=yes", "is-system-running"), self.system.calls[select + 1:reboot])

    async def test_wrong_slot_or_unbootable_fail_before_write(self):
        for attr, value in [("current", "a"), ("active", "a"), ("bootable", False), ("successful", False)]:
            with self.subTest(attr=attr):
                self.system = MockSystem()
                setattr(self.system, attr, value)
                with patch.object(m, "run_command", self.system.run):
                    with self.assertRaises(m.SafetyError):
                        await self.plugin.prepare_return()
                self.assertEqual(self.system.writes(), [])

    async def test_reboot_precondition_failure_never_selects(self):
        for attr, value in [("allow", "challenge"), ("allow", "no"), ("state", "degraded"),
                            ("preparing", True), ("scheduled", ["reboot", 123]),
                            ("firmware", True), ("bootmenu", 0), ("bootentry", "other"),
                            ("inhibitors", [["shutdown:sleep", "game", "save", "block", 1000, 9]]),
                            ("inhibitors", [["shutdown", "game", "save", "delay", 1000, 9]])]:
            with self.subTest(attr=attr, value=value):
                self.system = MockSystem()
                setattr(self.system, attr, value)
                with patch.object(m, "run_command", self.system.run):
                    with self.assertRaises(m.SafetyError):
                        await self.plugin.prepare_return()
                self.assertEqual(self.system.writes(), [])

    async def test_slot_and_reboot_conditions_rechecked_on_confirm(self):
        prepared = await self.plugin.prepare_return()
        self.system.active = "a"
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.writes(), [])

    async def test_script_error_or_wrong_readback_never_reboots(self):
        for mode in ["script-failure", "wrong-readback"]:
            with self.subTest(mode=mode):
                self.system = MockSystem()
                if mode == "script-failure":
                    self.system.fail = (m.SLOT, "android")
                else:
                    self.system.skip_select = True
                with patch.object(m, "run_command", self.system.run):
                    prepared = await self.plugin.prepare_return()
                    with self.assertRaises(m.SafetyError):
                        await self.plugin.confirm_return(prepared["token"])
                self.assertEqual(self.system.writes(), [(m.SLOT, "android")])

    async def test_new_inhibitor_after_selection_stops_reboot(self):
        prepared = await self.plugin.prepare_return()
        self.system.post_inhibitor = True
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.writes(), [(m.SLOT, "android")])

    async def test_duplicate_confirm_rejected_while_first_is_running(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = m.switch_operation
        async def delayed():
            entered.set()
            await release.wait()
            return await original()
        prepared = await self.plugin.prepare_return()
        patcher = patch.object(m, "switch_operation", delayed)
        patcher.start()
        self.addCleanup(patcher.stop)
        first = asyncio.create_task(self.plugin.confirm_return(prepared["token"]))
        await entered.wait()
        with self.assertRaises(m.SafetyError):
            await self.plugin.confirm_return(prepared["token"])
        release.set()
        await first
        self.assertEqual(len(self.system.writes()), 2)

    async def test_wrong_host_or_privilege_rejected_before_commands(self):
        for setting in [patch.object(m.sys, "platform", "darwin"), patch.object(m.os, "geteuid", return_value=1000)]:
            with setting, self.assertRaises(m.SafetyError):
                await self.plugin.prepare_return()
        self.assertEqual(self.system.calls, [])

    async def test_malformed_bus_json_fails_closed(self):
        with patch.object(m, "run_command", AsyncMock(return_value="bad json")):
            with self.assertRaises((m.SafetyError, ValueError)):
                await m.reboot_ready()

    async def test_remote_loader_binding_rejected_before_commands(self):
        with patch.dict(m.os.environ, {"SERVER_HOST": "0.0.0.0"}), self.assertRaises(m.SafetyError):
            await self.plugin.prepare_return()
        self.assertEqual(self.system.calls, [])

    async def test_prepare_unload_race_rejects_new_token(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_preflight():
            entered.set()
            await release.wait()
            return CONFIG
        with patch.object(m, "preflight", delayed_preflight):
            task = asyncio.create_task(self.plugin.prepare_return())
            await entered.wait()
            await self.plugin._unload()
            release.set()
            with self.assertRaises(m.SafetyError):
                await task
        self.assertIsNone(self.plugin._pending)
        with self.assertRaises(m.SafetyError):
            await self.plugin.prepare_return()
        self.assertEqual(self.system.writes(), [])

    async def test_reboot_failure_reports_verified_android_selection(self):
        self.system.fail = (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot")
        prepared = await self.plugin.prepare_return()
        with self.assertRaisesRegex(m.SafetyError, "Android A 已选为下次启动槽"):
            await self.plugin.confirm_return(prepared["token"])
        self.assertEqual(self.system.active, "a")
        self.assertEqual(self.system.writes(), [(m.SLOT, "android"), (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot")])


    async def test_malformed_typed_bus_fields_stop_before_selection(self):
        for attr, value in [("preparing", 0), ("scheduled", ["", False]),
                            ("firmware", 0), ("bootmenu", True),
                            ("inhibitors", [["sleep", "app", "save", "unknown", 1000, 9]]),
                            ("inhibitors", [["sleep", "app", "save", "block", "1000", 9]]),
                            ("inhibitors", [["sleep", "app", "save", "block", True, 9]])]:
            with self.subTest(attr=attr, value=value):
                self.system = MockSystem()
                setattr(self.system, attr, value)
                with patch.object(m, "run_command", self.system.run):
                    with self.assertRaises(m.SafetyError):
                        await self.plugin.prepare_return()
                self.assertEqual(self.system.writes(), [])


class DeploymentTests(unittest.TestCase):
    def test_invalid_config_rejected(self):
        bad_configs = [{}, {**CONFIG, "schema": True}, {**CONFIG, "approved": False}, {**CONFIG, "android_slot": "b"},
                       {**CONFIG, "linux_slot": "a"}, {**CONFIG, "slot_script_sha256": "bad"}]
        for cfg in bad_configs:
            with self.subTest(cfg=cfg), patch.object(m, "trusted_file", return_value=json.dumps(cfg).encode()):
                with self.assertRaises(m.SafetyError):
                    m.deployment()

    def test_script_digest_mismatch_rejected(self):
        with patch.object(m, "trusted_file", side_effect=[json.dumps(CONFIG).encode(), b"changed script"]):
            with self.assertRaisesRegex(m.SafetyError, "启动工具已改变"):
                m.deployment()

    def test_relative_path_refused(self):
        with self.assertRaises(m.SafetyError):
            m.trusted_file("relative")


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    class Proc:
        def __init__(self, stdout=b"ok", stderr=b""):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(stdout)
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(stderr)
            self.stderr.feed_eof()
            self.returncode = None
            self.pid = 54321
            self.waited = False

        async def wait(self):
            self.waited = True
            self.returncode = 0
            return 0

    async def test_both_output_streams_bounded_and_process_group_killed(self):
        for stream in ["stdout", "stderr"]:
            proc = self.Proc(**{stream: b"x" * 65537})
            with patch.object(m.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)) as spawn, patch.object(m.os, "killpg") as kill:
                with self.assertRaisesRegex(m.SafetyError, "过多数据"):
                    await m.run_command(m.QBOOT, "-c")
                kill.assert_called_once_with(proc.pid, m.signal.SIGKILL)
                self.assertTrue(proc.waited)
                self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    async def test_exited_leader_still_kills_descendant_group_on_overflow(self):
        proc = self.Proc(stdout=b"x" * 65537)
        proc.returncode = 0
        with patch.object(m.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)), patch.object(m.os, "killpg") as kill:
            with self.assertRaises(m.SafetyError):
                await m.run_command(m.SLOT, "android")
            kill.assert_called_once_with(proc.pid, m.signal.SIGKILL)

    async def test_invalid_utf8_fixed_error(self):
        with patch.object(m.asyncio, "create_subprocess_exec", AsyncMock(return_value=self.Proc(stdout=b"\xff"))):
            with self.assertRaisesRegex(m.SafetyError, "异常文本"):
                await m.run_command(m.QBOOT, "-c")

    async def test_process_start_error_fixed_message(self):
        with patch.object(m.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("private detail"))):
            with self.assertRaisesRegex(m.SafetyError, "系统工具无法启动") as ctx:
                await m.run_command(m.QBOOT, "-c")
            self.assertNotIn("private detail", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
