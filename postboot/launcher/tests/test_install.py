"""Host-only installer tests: every destination is inside a temporary HOME."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import install as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home with 'quote'"
        self.home.mkdir(mode=0o700)
        self.sources = self.root / "checkout"
        self.launcher = self.sources / "postboot/launcher"
        self.launcher.mkdir(parents=True)
        for name in ("install.py", "dual_mode.py", "steamvr_auto.py", "future_added.py"):
            (self.launcher / name).write_text("# fixture " + name + "\n")
        (self.launcher / "not-python.json").write_text("{}")
        route = self.sources / "postboot/vrchat/launch_vrchat_known_route.py"
        route.parent.mkdir(parents=True)
        route.write_text("# existing protected route\n")
        runtime = self.sources / "postboot/pcvr/runtime"
        runtime.mkdir(parents=True)
        for name in ("paths.py", "retry_gate.py", "future_runtime.py"):
            (runtime / name).write_text("# existing " + name + "\n")
        self.bundle = self.home / ".local/lib/caihong-vrchat-launcher"
        self.state = self.home / ".local/state/caihong-vrchat-launcher"

    def plan(self, **kwargs):
        return installer.plan_install(home=self.home, source_root=self.sources, **kwargs)

    def existing(self, path, content=b"original file\n"):
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o600)
        return path

    def snapshot(self):
        return {str(path.relative_to(self.home)): (stat.S_IMODE(path.lstat().st_mode),
                path.read_bytes() if path.is_file() and not path.is_symlink() else None)
                for path in self.home.rglob("*")}

    def test_dry_run_creates_nothing_and_collects_current_sorted_sources(self):
        before = self.snapshot()
        plan = self.plan()
        self.assertIsNone(installer.install(plan))
        self.assertEqual(before, self.snapshot())
        names = [str(item.destination.relative_to(self.bundle)) for item in plan.files]
        self.assertEqual(names, sorted(names))
        self.assertIn("future_added.py", names)
        self.assertIn("runtime/future_runtime.py", names)
        self.assertIn("vrchat/launch_vrchat_known_route.py", names)
        self.assertNotIn("not-python.json", names)
        (self.launcher / "added_after_first_plan.py").write_text("# dynamic\n")
        self.assertIn("added_after_first_plan.py", [item.destination.name for item in self.plan().files])

    def test_apply_private_bundle_backups_manifest_and_protected_paths(self):
        old = self.existing(self.bundle / "dual_mode.py")
        prefix = self.existing(self.home / ".local/share/cvrc-x64/protected", b"private-prefix")
        tool = self.existing(self.home / ".local/share/caihong-vrchat-fex-eac-tool/protected", b"private-tool")
        profile = self.existing(self.home / ".local/state/caihong-pcvr/server-fex-config.json", b"profile")
        original = old.read_bytes()
        manifest_path = installer.install(self.plan(), apply=True)
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["status"], "applied")
        self.assertEqual(old.read_bytes(), (self.launcher / "dual_mode.py").read_bytes())
        entries = {item["destination"]: item for item in manifest["files"]}
        entry = entries[str(old)]
        self.assertTrue(entry["existed"])
        self.assertEqual(Path(entry["backup"]).read_bytes(), original)
        self.assertEqual(entry["installed_sha256"], hashlib.sha256(old.read_bytes()).hexdigest())
        for root in (self.bundle, self.state):
            for path in [root, *root.rglob("*")]:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
                self.assertEqual(path.stat().st_uid, os.getuid())
        self.assertEqual(prefix.read_bytes(), b"private-prefix")
        self.assertEqual(tool.read_bytes(), b"private-tool")
        self.assertEqual(profile.read_bytes(), b"profile")
        self.assertFalse((self.home / ".config").exists())
        self.assertFalse(any(key in manifest for key in ("argv", "environment", "account", "username")))

    def test_rollback_preview_then_restore_only_owned_files_and_keep_directories(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        kept = self.existing(self.bundle / "unmanaged.txt", b"keep")
        manifest = installer.install(self.plan(), apply=True)
        before = self.snapshot()
        operations = installer.rollback(manifest, home=self.home)
        self.assertIn(old, operations)
        self.assertEqual(before, self.snapshot())
        installer.rollback(manifest.parent, home=self.home, apply=True)
        self.assertEqual(old.read_bytes(), b"before")
        self.assertEqual(kept.read_bytes(), b"keep")
        self.assertFalse((self.bundle / "future_added.py").exists())
        self.assertTrue((self.bundle / "runtime").is_dir())
        self.assertTrue(self.bundle.is_dir())
        self.assertTrue(manifest.is_file())
        self.assertEqual(json.loads(manifest.read_text())["status"], "rolled-back")
        self.assertEqual(installer.rollback(manifest, home=self.home, apply=True), ())

    def test_changed_file_refuses_entire_rollback_without_overwriting_user_edits(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        manifest = installer.install(self.plan(), apply=True)
        changed = self.bundle / "steamvr_auto.py"
        changed.write_bytes(b"user edit")
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.rollback(manifest, home=self.home, apply=True)
        self.assertEqual(before, self.snapshot())
        self.assertNotEqual(old.read_bytes(), b"before")
        self.assertEqual(changed.read_bytes(), b"user edit")

    def test_changed_between_plan_and_apply_is_preserved(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        plan = self.plan()
        old.write_bytes(b"changed after plan")
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.install(plan, apply=True)
        self.assertEqual(before, self.snapshot())

    def test_symlink_ancestors_and_direct_files_are_rejected_without_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / ".local").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            self.plan()
        self.assertEqual(list(outside.iterdir()), [])
        (self.home / ".local").unlink()
        self.bundle.mkdir(mode=0o700, parents=True)
        external = self.root / "external.py"
        external.write_text("outside")
        (self.bundle / "dual_mode.py").symlink_to(external)
        with self.assertRaises(installer.InstallError):
            installer.install(self.plan(), apply=True)
        self.assertEqual(external.read_text(), "outside")

    def test_rollback_rejects_replaced_bundle_ancestor(self):
        manifest = installer.install(self.plan(), apply=True)
        moved = self.bundle.with_name("saved-bundle")
        self.bundle.rename(moved)
        self.bundle.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            installer.rollback(manifest, home=self.home, apply=True)
        self.assertTrue((moved / "dual_mode.py").exists())

    def test_nonprivate_existing_destination_and_directory_are_rejected(self):
        old = self.existing(self.bundle / "dual_mode.py")
        old.chmod(0o644)
        with self.assertRaises(installer.InstallError):
            self.plan()
        old.chmod(0o600)
        self.bundle.chmod(0o755)
        with self.assertRaises(installer.InstallError):
            self.plan()

    def test_templates_quote_space_and_apostrophe_paths_without_env_mutation(self):
        driver = self.root / "driver's path/custom icd.json"
        before = dict(os.environ)
        options = installer.launch_options(home=self.home, steamvr_vk_driver=driver)
        self.assertEqual(dict(os.environ), before)
        vrchat = shlex.split(options["438100"])
        steamvr = shlex.split(options["250820"])
        prefix = self.home / ".local/share/cvrc-x64"
        self.assertEqual(vrchat, ["env", "STEAM_COMPAT_DATA_PATH=" + str(prefix),
                                 "EAC_LAUNCHERDIR=" + str(prefix / "pfx/drive_c/users/steamuser/AppData/Roaming/EasyAntiCheat"),
                                 "PROTON_EAC_RUNTIME=" + str(self.home / ".local/share/Steam/steamapps/common/Proton EasyAntiCheat Runtime"),
                                 "WINEDEBUG=-all", "PROTON_USE_XALIA=0", "python3",
                                 str(self.bundle / "dual_mode.py"), "--mode", "auto", "--", "%command%",
                                 "--enable-avpro-in-proton"])
        self.assertNotIn("--no-vr", vrchat)
        self.assertEqual(vrchat.count("--enable-avpro-in-proton"), 1)
        self.assertEqual(vrchat[-2:], ["%command%", "--enable-avpro-in-proton"])
        self.assertEqual(steamvr, ["env", "FEX_APP_CONFIG=" + str(self.home / ".local/state/caihong-pcvr/server-fex-config.json"),
                                  "VK_DRIVER_FILES=" + str(driver), "python3", str(self.bundle / "steamvr_auto.py"), "--", "%command%"])
        self.assertIn("VK_DRIVER_FILES=" + installer.DEFAULT_STEAMVR_VK_DRIVER,
                      " ".join(shlex.split(installer.launch_options(home=self.home)["250820"])))

    def test_missing_installed_file_and_tampered_backup_block_rollback(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        manifest = installer.install(self.plan(), apply=True)
        removed = self.bundle / "future_added.py"
        data = removed.read_bytes()
        removed.unlink()
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.rollback(manifest, home=self.home, apply=True)
        self.assertEqual(before, self.snapshot())
        removed.write_bytes(data)
        removed.chmod(0o600)
        entries = json.loads(manifest.read_text())["files"]
        backup = Path(next(entry["backup"] for entry in entries if entry["destination"] == str(old)))
        backup.write_bytes(b"tampered original")
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.rollback(manifest, home=self.home, apply=True)
        self.assertEqual(before, self.snapshot())

    def test_source_and_state_symlinks_are_rejected(self):
        original = self.launcher / "future_added.py"
        original.unlink()
        original.symlink_to(self.launcher / "dual_mode.py")
        with self.assertRaises(installer.InstallError):
            self.plan()
        original.unlink()
        original.write_bytes(b"# fixture")
        state_parent = self.home / ".local/state"
        state_parent.mkdir(mode=0o700, parents=True)
        outside = self.root / "outside-state"
        outside.mkdir()
        self.state.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            self.plan()
        self.assertEqual(list(outside.iterdir()), [])

    def test_owner_checks_cover_destinations_and_ancestors(self):
        old = self.existing(self.bundle / "dual_mode.py")
        uid = os.getuid()
        with patch.object(installer.os, "getuid", return_value=uid + 1):
            with self.assertRaises(installer.InstallError):
                self.plan()
        (self.home / ".local").chmod(0o777)
        with self.assertRaises(installer.InstallError):
            self.plan()
        self.assertEqual(old.read_bytes(), b"original file\n")

    def test_manifest_cannot_target_unrelated_files(self):
        manifest = installer.install(self.plan(), apply=True)
        record = json.loads(manifest.read_text())
        outside = self.existing(self.home / "outside.py", b"precious")
        record["files"][0]["destination"] = str(outside)
        manifest.write_text(json.dumps(record))
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.rollback(manifest, home=self.home, apply=True)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(outside.read_bytes(), b"precious")

    def test_apply_failure_restores_completed_files_and_keeps_recovery_record(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        original_write = installer._write
        failed = False

        def fail_once(path, data, home, **kwargs):
            nonlocal failed
            if path == self.bundle / "steamvr_auto.py" and not failed:
                failed = True
                raise OSError("injected write failure")
            return original_write(path, data, home, **kwargs)

        with patch.object(installer, "_write", side_effect=fail_once):
            with self.assertRaises(installer.InstallError):
                installer.install(self.plan(), apply=True)
        self.assertEqual(old.read_bytes(), b"before")
        self.assertFalse((self.bundle / "future_added.py").exists())
        manifest, = self.state.glob("transactions/*/manifest.json")
        self.assertEqual(json.loads(manifest.read_text())["status"], "rolled-back")

    def test_interrupted_rollback_can_resume_without_touching_restored_files(self):
        old = self.existing(self.bundle / "dual_mode.py", b"before")
        manifest = installer.install(self.plan(), apply=True)
        remove = installer._remove
        calls = 0

        def interrupt(path, home, expected):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected rollback interruption")
            return remove(path, home, expected)

        with patch.object(installer, "_remove", side_effect=interrupt):
            with self.assertRaises(OSError):
                installer.rollback(manifest, home=self.home, apply=True)
        installer.rollback(manifest, home=self.home, apply=True)
        self.assertEqual(old.read_bytes(), b"before")
        self.assertFalse((self.bundle / "future_added.py").exists())
        self.assertEqual(json.loads(manifest.read_text())["status"], "rolled-back")

    def test_cli_defaults_to_dry_run_and_prints_app_specific_templates(self):
        before = self.snapshot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = installer.main([], home=self.home, source_root=self.sources)
        self.assertEqual(code, 0)
        self.assertEqual(before, self.snapshot())
        self.assertIn("438100", output.getvalue())
        self.assertIn("250820", output.getvalue())
        self.assertNotIn("--no-vr", output.getvalue())


if __name__ == "__main__":
    unittest.main()
