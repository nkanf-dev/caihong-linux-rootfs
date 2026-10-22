# SPDX-License-Identifier: GPL-2.0-only
"""Offline fixtures only. Run with native Linux Python; never access a device."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch
import zlib

SOURCE = Path(__file__).resolve().parents[2] / "rootfs/archlinuxarm/usr/local/libexec/caihong-slot.py"
spec = importlib.util.spec_from_file_location("caihong_slot_tested", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CONFIG = {"schema": 1, "approved": True, "android_slot": "a", "linux_slot": "b",
          "linux_partlabel": "linux", "linux_bytes": 68719476736,
          "kernel_release": "7.2.0-g80730b2e1754", "qbootctl_sha256": "a" * 64,
          "ufs_boot_lun_path": "/sys/devices/platform/soc@0/1d84000.ufshc/attributes/boot_lun_enabled"}
IDENTITY = {"boot_id": "dc29c221-b17d-4472-8979-fb6c245f4ec9", "root_device": "/dev/sda15",
            "root_dev": [8, 15], "root_bytes": 68719476736, "partlabel": "linux",
            "kernel_release": CONFIG["kernel_release"]}


def state(slot="b"):
    return {"active": slot, "ufs_lun": 1 if slot == "a" else 2,
            "bootable": {"a": True, "b": True}, "successful": {"a": True, "b": True},
            "tables": {}, "pairs": ["boot", "dtbo"], "partitions": {}}


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.current = state()
        self.commands = []
        self.fail = None
        self.changed_identity = False
        self.tool_checks = 0
        self.ready_calls = 0
        self.same_layout = True
        self.events = []

    def run_tool(self, argv, timeout):
        self.commands.append(tuple(argv))
        if argv == [m.QBOOT, "-s", "a"]:
            self.current = state("a")
            self.current["successful"]["a"] = False
        if self.fail == tuple(argv):
            raise m.SwitchError("tool failed")
        return ""

    def ready(self):
        self.ready_calls += 1
        if self.fail == "post-inhibitor" and self.ready_calls == 2:
            raise m.SwitchError("shutdown inhibited")

    def execute(self, target="a", reboot=True):
        with patch.object(m, "read_identity", side_effect=lambda cfg: ({**IDENTITY, "boot_id": "changed"} if self.changed_identity else IDENTITY.copy())),              patch.object(m, "read_state", side_effect=lambda cfg: copy.deepcopy(self.current)),              patch.object(m, "verify_tools"), patch.object(m, "reboot_ready", side_effect=self.ready),              patch.object(m, "run_command", side_effect=self.run_tool),              patch.object(m, "verify_transition", side_effect=lambda before, after: None if self.same_layout else (_ for _ in ()).throw(m.SwitchError("layout changed"))),              patch.object(m, "event", side_effect=lambda phase, **fields: self.events.append((phase, fields))):
            return m.switch(CONFIG, target, reboot)

    def test_first_selection_then_normal_reboot(self):
        result = self.execute()
        self.assertTrue(result["reboot_requested"])
        self.assertTrue(result["selection_written"])
        self.assertEqual(self.commands, [(m.QBOOT, "-s", "a"), (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot")])
        self.assertEqual(self.ready_calls, 2)

    def test_already_android_only_reboots_without_set_active_or_success_guard(self):
        self.current = state("a")
        self.current["successful"]["a"] = False
        result = self.execute()
        self.assertFalse(result["selection_written"])
        self.assertEqual(self.commands, [(m.SYSTEMCTL, "--check-inhibitors=yes", "reboot")])

    def test_without_reboot_only_selects(self):
        result = self.execute(reboot=False)
        self.assertFalse(result["reboot_requested"])
        self.assertEqual(self.commands, [(m.QBOOT, "-s", "a")])
        self.assertEqual(self.ready_calls, 0)

    def test_already_target_no_reboot_is_no_write(self):
        self.current = state("a")
        self.execute(reboot=False)
        self.assertEqual(self.commands, [])

    def test_unapproved_config_never_runs_tool(self):
        with self.assertRaises(m.SwitchError):
            m.switch({**CONFIG, "approved": False}, "a", True)
        self.assertEqual(self.commands, [])

    def test_unbootable_target_never_selects(self):
        self.current["bootable"]["a"] = False
        with self.assertRaises(m.SwitchError):
            self.execute()
        self.assertEqual(self.commands, [])

    def test_unsuccessful_target_requires_first_boot_evidence(self):
        self.current["successful"]["a"] = False
        with self.assertRaises(m.SwitchError):
            self.execute()
        self.assertEqual(self.commands, [])

    def test_selection_failure_can_leave_active_android_but_never_reboots(self):
        self.fail = (m.QBOOT, "-s", "a")
        with self.assertRaisesRegex(m.SwitchError, "可能已改变"):
            self.execute()
        self.assertEqual(self.current["active"], "a")
        self.assertEqual(self.commands, [(m.QBOOT, "-s", "a")])

    def test_inhibitor_after_selection_stops_reboot_and_next_confirm_skips_write(self):
        self.fail = "post-inhibitor"
        with self.assertRaisesRegex(m.SwitchError, "已选"):
            self.execute()
        self.assertEqual(self.commands, [(m.QBOOT, "-s", "a")])
        self.fail = None
        self.execute()
        self.assertEqual(self.commands.count((m.QBOOT, "-s", "a")), 1)
        self.assertEqual(self.commands[-1], (m.SYSTEMCTL, "--check-inhibitors=yes", "reboot"))

    def test_unexpected_layout_change_stops_reboot(self):
        self.same_layout = False
        with self.assertRaises(m.SwitchError):
            self.execute()
        self.assertNotIn((m.SYSTEMCTL, "--check-inhibitors=yes", "reboot"), self.commands)

    def test_identity_change_after_selection_stops_reboot(self):
        original = self.run_tool
        def change(argv, timeout):
            result = original(argv, timeout)
            if argv[0] == m.QBOOT:
                self.changed_identity = True
            return result
        self.run_tool = change
        with self.assertRaisesRegex(m.SwitchError, "身份"):
            self.execute()
        self.assertEqual(self.commands, [(m.QBOOT, "-s", "a")])

    def test_no_command_ever_uses_current_fallback_or_marks_successful(self):
        self.execute()
        self.assertFalse(any("-c" in c or "-m" in c or "-u" in c for c in self.commands))


class ValidationTests(unittest.TestCase):
    def test_strict_config(self):
        self.assertEqual(m.validate_config(CONFIG), CONFIG)
        for changed in [{"approved": 1}, {"schema": True}, {"android_slot": "b"},
                        {"linux_bytes": True}, {"linux_partlabel": "userdata"},
                        {"qbootctl_sha256": ""}, {"ufs_boot_lun_path": "/tmp/lun"},
                        {"extra": 1}]:
            with self.subTest(changed=changed), self.assertRaises(m.SwitchError):
                m.validate_config({**CONFIG, **changed})

    def test_exact_boot_slot_keys_and_conflicts(self):
        m.check_boot_parameters("root=PARTLABEL=linux quiet", "", "b", "linux")
        m.check_boot_parameters("root=PARTLABEL=linux androidboot.slot_suffix=_b", "", "b", "linux")
        m.check_boot_parameters("root=PARTLABEL=linux", 'androidboot.slot_suffix = "_b"', "b", "linux")
        for args, extra in [("root=PARTLABEL=userdata", ""),
                            ("root=PARTLABEL=linux slot_suffix=_a", ""),
                            ("root=PARTLABEL=linux androidboot.slot_suffix=_b slot_suffix=_a", ""),
                            ("root=PARTLABEL=linux", 'androidboot.slot_suffix = "_a"')]:
            with self.subTest(args=args), self.assertRaises(m.SwitchError):
                m.check_boot_parameters(args, extra, "b", "linux")

    def test_raw_state_rejects_ufs_mismatch_and_two_active_slots(self):
        attrs = {"boot_a": 0x40 << 48, "boot_b": 0x44 << 48,
                 "dtbo_a": 0x40 << 48, "dtbo_b": 0x44 << 48}
        self.assertEqual(m.selection_from_attributes(attrs, ["boot", "dtbo"], 2)["active"], "b")
        for changes, lun in [({}, 1), ({"boot_a": 0x44 << 48}, 2), ({"dtbo_b": 0x40 << 48}, 2)]:
            with self.subTest(changes=changes, lun=lun), self.assertRaises(m.SwitchError):
                m.selection_from_attributes({**attrs, **changes}, ["boot", "dtbo"], lun)

    def test_bus_inhibitor_rejects_shutdown_only(self):
        m.check_inhibitors([["sleep", "net", "save", "delay", 0, 12]])
        for mode in ["block", "delay", "block-weak"]:
            with self.assertRaises(m.SwitchError):
                m.check_inhibitors([["shutdown:sleep", "game", "save", mode, 1000, 13]])
        with self.assertRaises(m.SwitchError):
            m.check_inhibitors([["shutdown", "bad"]])

    def test_transition_rejects_geometry_and_unrelated_changes(self):
        entry = bytes(128)
        before = {"tables": {"disk": {"entries": {"boot_a": entry, "linux": entry}, "identity": [1, 2]}}, "pairs": ["boot"]}
        after = copy.deepcopy(before)
        allowed = bytearray(entry); allowed[:16] = b"x" * 16; allowed[54] = 15
        after["tables"]["disk"]["entries"]["boot_a"] = bytes(allowed)
        m.verify_transition(before, after)
        for offset in [16, 32, 40, 55, 56]:
            bad = copy.deepcopy(after); changed = bytearray(entry); changed[offset] = 1
            bad["tables"]["disk"]["entries"]["linux"] = bytes(changed)
            with self.assertRaises(m.SwitchError):
                m.verify_transition(before, bad)


class GPTTests(unittest.TestCase):
    def fixture(self):
        sectors, block = 128, 512
        image = bytearray(sectors * block)
        entries = bytearray(4 * 128)
        entries[:16] = b"t" * 16; entries[16:32] = b"u" * 16
        struct.pack_into("<QQQ", entries, 32, 8, 20, 0x44 << 48)
        name = "boot_b".encode("utf-16-le"); entries[56:56 + len(name)] = name
        image[2 * block:3 * block] = entries
        image[126 * block:127 * block] = entries
        def header(current, other, table_lba):
            data = bytearray(block); data[:8] = b"EFI PART"
            struct.pack_into("<IIIIQQQQ16sQIII", data, 8, 0x10000, 92, 0, 0,
                             current, other, 3, 125, b"g" * 16, table_lba, 4, 128, zlib.crc32(entries))
            struct.pack_into("<I", data, 16, zlib.crc32(data[:92])); return data
        image[block:2 * block] = header(1, 127, 2)
        image[127 * block:128 * block] = header(127, 1, 126)
        return image, block

    def parse(self, image, block):
        return m.parse_gpt(lambda offset, size: bytes(image[offset:offset + size]), len(image), block)

    def test_valid_primary_and_backup(self):
        image, block = self.fixture()
        parsed = self.parse(image, block)
        self.assertEqual(parsed["entries"]["boot_b"][54], 0x44)

    def test_header_array_crc_and_backup_mismatch_fail(self):
        for offset in [512 + 20, 1024 + 54, 126 * 512 + 54, 127 * 512 + 20]:
            image, block = self.fixture(); image[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(m.SwitchError):
                self.parse(image, block)


class RunnerTests(unittest.TestCase):
    def test_fixed_environment_timeout_kills_group_without_unbounded_wait(self):
        import subprocess
        process = Mock(pid=12345, returncode=None)
        process.communicate.side_effect = [subprocess.TimeoutExpired(["tool"], 1),
                                           subprocess.TimeoutExpired(["tool"], 1)]
        with patch.object(m.subprocess, "Popen", return_value=process) as popen,              patch.object(m.os, "killpg") as kill, patch.object(m, "event"):
            with self.assertRaisesRegex(m.SwitchError, "超时"):
                m.run_command([m.QBOOT, "-s", "a"], 1)
        kill.assert_called_once_with(12345, m.signal.SIGKILL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("HOME", popen.call_args.kwargs["env"])
        self.assertEqual(process.communicate.call_count, 2)

    def test_tool_stderr_retained_in_event(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (None, None)
        def spawn(*args, **kwargs):
            kwargs["stderr"].write(b"ufs write failed")
            return process
        with patch.object(m.subprocess, "Popen", side_effect=spawn), patch.object(m, "event") as log:
            with self.assertRaises(m.SwitchError):
                m.run_command([m.QBOOT, "-s", "a"], 1)
        self.assertIn("ufs write failed", str(log.call_args_list))


if __name__ == "__main__":
    unittest.main()
