# SPDX-License-Identifier: MIT
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("power_install", Path(__file__).parents[1] / "install.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.homebrew = self.base / "homebrew"
        (self.homebrew / "plugins").mkdir(parents=True)
        self.payload = self.base / "payload"
        self.payload.mkdir()
        for rel in m.PAYLOAD:
            p = self.payload / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture " + rel)
        self.slot = self.base / "caihong-slot"
        self.slot.write_text("fixture trusted script")
        self.qboot = self.base / "qbootctl"
        self.qboot.write_text("fixture trusted binary")
        self.config = self.base / "config.json"
        self.qsha = m.digest(self.qboot)
        self.patches = [patch.object(m, "ROOT", self.payload), patch.object(m, "REQUIRED_UID", m.os.geteuid()), patch.object(m, "CONFIG", self.config),
                        patch.object(m, "SLOT", self.slot), patch.object(m, "QBOOT", self.qboot),
                        patch.object(m, "EXPECTED_SLOT_SHA256", m.digest(self.slot)),
                        patch.object(m, "root_path"), patch.object(m.os, "access", return_value=True)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def install(self, **kwargs):
        return m.install(self.homebrew, kwargs.get("sha", self.qsha), kwargs.get("approve", True), kwargs.get("loader", "3.3.0"))

    def test_install_remove_only_owned_files_and_preserve_other_plugin(self):
        other = self.homebrew / "plugins/Other"
        other.mkdir()
        (other / "source").write_text("keep")
        result = self.install()
        self.assertEqual(result["activation"], "next normal Decky/Steam startup")
        cfg = json.loads(self.config.read_text())
        self.assertEqual((cfg["android_slot"], cfg["linux_slot"]), ("a", "b"))
        self.assertTrue(cfg["approved"])
        with self.assertRaises(ValueError):
            self.install()
        m.remove(self.homebrew)
        self.assertEqual((other / "source").read_text(), "keep")
        self.assertFalse(self.config.exists())
        self.assertFalse((self.homebrew / "plugins" / m.NAME).exists())

    def test_changed_plugin_or_extra_file_preserved(self):
        self.install()
        target = self.homebrew / "plugins" / m.NAME
        (target / "main.py").write_text("changed")
        with self.assertRaises(ValueError):
            m.remove(self.homebrew)
        self.assertTrue(self.config.exists())
        self.assertTrue((target / "main.py").exists())

    def test_changed_config_preserved(self):
        self.install()
        self.config.write_text("changed")
        with self.assertRaises(ValueError):
            m.remove(self.homebrew)
        self.assertEqual(self.config.read_text(), "changed")

    def test_no_approval_or_wrong_version_or_digest_no_files_written(self):
        for kwargs in [{"approve": False}, {"loader": "3.3.1"}, {"sha": "f" * 64}, {"sha": "bad"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.install(**kwargs)
            self.assertFalse(self.config.exists())
            self.assertFalse((self.homebrew / "plugins" / m.NAME).exists())

    def test_symlink_homebrew_refused(self):
        link = self.base / "link"
        link.symlink_to(self.homebrew, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.target_path(link)

    def test_dist_symlink_refused_preserves_external_files(self):
        self.install()
        target = self.homebrew / "plugins" / m.NAME
        original = target / "dist"
        outside = self.base / "outside"
        original.rename(outside)
        original.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            m.remove(self.homebrew)
        self.assertTrue((outside / "index.js").exists())
        self.assertTrue(self.config.exists())

    def test_writable_plugins_namespace_rejected(self):
        (self.homebrew / "plugins").chmod(0o777)
        with self.assertRaisesRegex(ValueError, "root-owned"):
            self.install()
        self.assertFalse(self.config.exists())

    def test_parent_swap_cannot_redirect_anchored_write(self):
        anchor = self.base / "anchor"
        anchor.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        fd = m.open_dir(anchor)
        try:
            moved = self.base / "moved"
            anchor.rename(moved)
            anchor.symlink_to(outside, target_is_directory=True)
            m.write_at("owned", fd, b"safe")
            self.assertEqual((moved / "owned").read_bytes(), b"safe")
            self.assertFalse((outside / "owned").exists())
        finally:
            m.os.close(fd)


if __name__ == "__main__":
    unittest.main()
