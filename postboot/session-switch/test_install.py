"""Host-only tests. No candidate executable or system service is run."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("sddm_installer", Path(__file__).with_name("install.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        # Fixture permissions must not inherit a caller's permissive device umask.
        previous_umask = os.umask(0o022)
        self.addCleanup(os.umask, previous_umask)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "target"
        self.root.mkdir(mode=0o700)
        self.source = self.root.parent / "candidate"
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HH", header, 16, 3, 183)
        self.binary = bytes(header) + b"test-only ELF fixture, never executed"
        self.source.write_bytes(self.binary)
        self.sha = hashlib.sha256(self.binary).hexdigest()
        self.evidence = self.root.parent / "build.json"
        self.evidence_data = {
            "native_build": {"system": "Linux", "machine": "aarch64"},
            "success": True, "regression": {"green_cases": 8},
            "daemon": {"sha256": self.sha},
        }
        self.save_evidence()
        self.runner = mock.Mock()
        self.inst = installer.Installer(self.root, os.getuid(), os.getgid(), self.runner)
        self.put(installer.VENDOR, b"[Unit]\nDescription=Vendor\n[Service]\nExecStart=/usr/bin/sddm --test-mode\nRestart=always\n")
        self.put("/usr/bin/sddm", b"original packaged daemon")
        self.preflight = mock.patch.object(installer, "native_preflight")
        self.preflight.start()
        self.addCleanup(self.preflight.stop)

    def save_evidence(self):
        self.evidence.write_text(json.dumps(self.evidence_data))

    def put(self, logical, data, mode=0o644):
        path = self.inst.path(logical)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def apply(self):
        return self.inst.apply(self.source, self.sha, self.evidence)

    def test_readonly_plan_preserves_arguments_and_defaults(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        _, plan = self.inst.plan(self.source, self.sha, self.evidence)
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))
        self.assertEqual(plan["action"], "plan-install")
        self.assertEqual(plan["dropin_text"], "[Service]\nExecStart=\nExecStart=" +
                         f"{installer.PRIVATE}/{self.sha}/sddm --test-mode\n")
        self.assertNotIn("Restart=", plan["dropin_text"])
        self.runner.assert_not_called()
        installer.native_preflight.assert_not_called()

    def test_stage_and_rollback_when_previous_absent(self):
        result = self.apply()
        candidate = self.inst.path(result["private_executable"])
        self.assertEqual(stat.S_IMODE(self.inst.path("/usr/local/libexec").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.inst.path(installer.PRIVATE).stat().st_mode), 0o700)
        self.assertEqual(candidate.read_bytes(), self.binary)
        self.assertEqual(stat.S_IMODE(candidate.stat().st_mode), 0o755)
        self.assertEqual(candidate.stat().st_uid, os.getuid())
        self.assertEqual(self.inst.path("/usr/bin/sddm").read_bytes(), b"original packaged daemon")
        receipt_path = self.inst.path(result["receipt"])
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        record = json.loads(receipt_path.read_text())
        self.assertEqual(record["status"], "staged")
        self.assertEqual(base64.b64decode(record["candidate"]["build_evidence"]["bytes_base64"]),
                         self.evidence.read_bytes())
        self.assertEqual(self.inst.rollback(result["receipt"])["action"], "plan-rollback")
        self.assertTrue(self.inst.path(installer.DROPIN).exists())
        self.assertEqual(self.inst.rollback(result["receipt"], apply=True)["action"], "rolled-back")
        self.assertFalse(self.inst.path(installer.DROPIN).exists())
        self.assertTrue(candidate.exists())
        self.runner.assert_not_called()

    def test_backup_and_restore_exact_previous_bytes_mode_owner(self):
        previous = b"# prior\r\n[Service]\r\nEnvironment=EXAMPLE=yes\r\n\x00"
        old = self.put(installer.DROPIN, previous, 0o640)
        before = old.stat()
        result = self.apply()
        receipt = json.loads(self.inst.path(result["receipt"]).read_text())
        backup = self.inst.path(result["receipt"]).with_name("previous-dropin")
        self.assertEqual(backup.read_bytes(), previous)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(receipt["previous"]["uid"], before.st_uid)
        self.inst.rollback(result["receipt"], apply=True)
        self.assertEqual(old.read_bytes(), previous)
        self.assertEqual(stat.S_IMODE(old.stat().st_mode), 0o640)
        self.assertEqual((old.stat().st_uid, old.stat().st_gid), (before.st_uid, before.st_gid))
        self.inst.rollback(result["receipt"], apply=True)  # Idempotent.

    def test_reject_hash_elf_and_source_symlink(self):
        with self.assertRaises(installer.InstallError):
            self.inst.plan(self.source, "0" * 64, self.evidence)
        self.source.write_bytes(b"not ELF")
        with self.assertRaises(installer.InstallError):
            installer.candidate(self.source, hashlib.sha256(b"not ELF").hexdigest(), self.evidence)
        self.source.unlink()
        self.source.symlink_to(self.evidence)
        with self.assertRaises(OSError):
            installer.candidate(self.source, self.sha, self.evidence)

    def test_evidence_requires_native_success_and_matching_daemon(self):
        for field, value in (("success", False), ("native_build", {"system": "Darwin", "machine": "arm64"}),
                             ("daemon", {"sha256": "0" * 64}), ("regression", {"green_cases": 7})):
            with self.subTest(field=field):
                saved = self.evidence_data[field]
                self.evidence_data[field] = value
                self.save_evidence()
                with self.assertRaises(installer.InstallError):
                    self.inst.plan(self.source, self.sha, self.evidence)
                self.evidence_data[field] = saved
        self.evidence_data.pop("regression")
        self.save_evidence()
        _, plan = self.inst.plan(self.source, self.sha, self.evidence)
        self.assertEqual(plan["candidate"]["regression_summary"], "omitted from supplied evidence")

    def test_reject_symlink_dropin_and_parent_escape(self):
        outside = self.root.parent / "outside"
        outside.write_bytes(b"unchanged")
        dropin = self.inst.path(installer.DROPIN)
        dropin.parent.mkdir(parents=True)
        dropin.symlink_to(outside)
        with self.assertRaises(installer.InstallError):
            self.apply()
        self.assertEqual(outside.read_bytes(), b"unchanged")
        dropin.unlink()
        dropin.parent.rmdir()
        dropin.parent.symlink_to(self.root.parent)
        with self.assertRaises(installer.InstallError):
            self.apply()
        with self.assertRaises(installer.InstallError):
            self.inst.path("/etc/../outside")

    def test_reject_world_writable_and_foreign_owner_targets(self):
        path = self.put(installer.DROPIN, b"prior", 0o666)
        with self.assertRaises(installer.InstallError):
            self.apply()
        path.chmod(0o644)
        metadata = path.lstat()
        foreign = mock.Mock(wraps=metadata)
        foreign.st_mode = metadata.st_mode
        foreign.st_uid = os.getuid() + 1
        foreign.st_nlink = 1
        with mock.patch.object(Path, "lstat", return_value=foreign):
            with self.assertRaises(installer.InstallError):
                self.inst.trusted(installer.DROPIN)

    def test_reject_foreign_execstart_and_changed_dropin_rollback(self):
        self.put("/etc/systemd/system/sddm.service.d/50-foreign.conf", b"[Service]\nExecStart=/opt/other\n")
        with self.assertRaises(installer.InstallError):
            self.apply()
        self.inst.path("/etc/systemd/system/sddm.service.d/50-foreign.conf").unlink()
        result = self.apply()
        self.inst.path(installer.DROPIN).write_bytes(b"operator change")
        with self.assertRaises(installer.InstallError):
            self.inst.rollback(result["receipt"], apply=True)
        self.assertEqual(self.inst.path(installer.DROPIN).read_bytes(), b"operator change")

    def test_selinux_failure_restores_previous_dropin(self):
        old = self.put(installer.DROPIN, b"previous exact bytes", 0o640)
        self.put("/usr/bin/chcon", b"helper")
        self.put("/usr/sbin/restorecon", b"helper")
        self.runner.side_effect = [None, subprocess.CalledProcessError(1, "restorecon")]
        with mock.patch.object(self.inst, "selinux_enabled", return_value=True), \
                mock.patch.object(installer.os, "getxattr", return_value=b"system_u:object_r:etc_t:s0\0"), \
                mock.patch.object(installer.os, "setxattr") as set_label:
            with self.assertRaises(installer.InstallError):
                self.apply()
        self.assertEqual(old.read_bytes(), b"previous exact bytes")
        self.assertEqual(stat.S_IMODE(old.stat().st_mode), 0o640)
        set_label.assert_called_once()
        records = list(self.root.glob("var/lib/caihong-sddm/receipts/*/receipt.json"))
        self.assertEqual(json.loads(records[0].read_text())["status"], "rolled_back_after_error")
        calls = self.runner.call_args_list
        self.assertIn("--reference=", calls[0].args[0][1])
        self.assertTrue(calls[1].args[0][0].endswith("restorecon"))
        self.assertFalse(any("systemctl" in str(call) for call in calls))

    def test_selinux_tool_alias_keeps_restorecon_basename(self):
        self.put("/usr/sbin/setfiles", b"multicall helper", 0o755)
        alias = self.inst.path("/usr/sbin/restorecon")
        alias.symlink_to("setfiles")
        self.inst.command("/usr/sbin/restorecon", "-F", "--", "/test")
        self.assertEqual(self.runner.call_args.args[0][0], str(alias))
        self.assertNotIn("setfiles", self.runner.call_args.args[0][0])

    def test_receipt_cannot_select_arbitrary_targets_or_tampered_backup(self):
        with self.assertRaises(installer.InstallError):
            self.inst.rollback("/tmp/receipt.json", apply=True)
        self.put(installer.DROPIN, b"prior")
        result = self.apply()
        backup = self.inst.path(result["receipt"]).with_name("previous-dropin")
        backup.write_bytes(b"tampered")
        with self.assertRaises(installer.InstallError):
            self.inst.rollback(result["receipt"], apply=True)


class FixtureUmaskTests(unittest.TestCase):
    def test_fixture_uses_secure_mask_and_restores_permissive_caller(self):
        caller_umask = os.umask(0)
        self.addCleanup(os.umask, caller_umask)
        fixture = InstallerTests("test_readonly_plan_preserves_arguments_and_defaults")
        try:
            fixture.setUp()
            self.assertEqual(stat.S_IMODE(fixture.inst.path("/usr").stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(fixture.inst.path("/usr/lib").stat().st_mode), 0o755)
            fixture.put("/etc/fixture.conf", b"fixture")
            self.assertEqual(stat.S_IMODE(fixture.inst.path("/etc").stat().st_mode), 0o755)
            with self.assertRaises(installer.InstallError):
                fixture.put(installer.DROPIN, b"untrusted", 0o666)
                fixture.inst.plan(fixture.source, fixture.sha, fixture.evidence)
        finally:
            fixture.doCleanups()
        restored_umask = os.umask(0)
        self.assertEqual(restored_umask, 0)


class NativePreflightTests(unittest.TestCase):
    def test_native_linux_aarch64_root_only(self):
        for system, machine, uid, accepted in (
                ("Darwin", "arm64", 0, False), ("Linux", "x86_64", 0, False),
                ("Linux", "aarch64", 1000, False), ("Linux", "aarch64", 0, True)):
            with self.subTest(system=system, machine=machine, uid=uid), \
                    mock.patch.object(platform, "system", return_value=system), \
                    mock.patch.object(platform, "machine", return_value=machine), \
                    mock.patch.object(os, "geteuid", return_value=uid):
                if accepted:
                    installer.native_preflight()
                else:
                    with self.assertRaises(installer.InstallError):
                        installer.native_preflight()


if __name__ == "__main__":
    unittest.main()
