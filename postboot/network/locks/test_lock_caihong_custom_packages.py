import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('hold', HERE/'lock_caihong_custom_packages.py')
hold = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hold)

class TransformTests(unittest.TestCase):
    def test_exact_names_and_separate_mesa_status(self):
        self.assertEqual(len(hold.CUSTOM), 33)
        self.assertEqual(len(hold.MESA_BASELINE), 6)
        self.assertEqual(len(set(hold.HOLDS)), 39)
        self.assertTrue(all(not any(c in name for c in '*?[]') for name in hold.HOLDS))
        self.assertNotIn('systemd', hold.HOLDS)
        self.assertNotIn('kernel', hold.HOLDS)
    def test_existing_exclusions_and_other_settings_preserved(self):
        original = b'# keep\n[main]\ninstallonly_limit=3\nexcludepkgs=old*,other\n# stay\n[repo]\nexclude=repo-only\n'
        updated, existing = hold.transform(original)
        self.assertEqual(existing, ['old*', 'other'])
        self.assertIn(b'excludepkgs=old*,other,', updated)
        self.assertEqual(updated.split(b'\n# stay', 1)[1], original.split(b'\n# stay', 1)[1])
        self.assertIn(b'installonly_limit=3\n', updated)
        self.assertEqual(hold.transform(updated)[0], updated)
    def test_crlf_and_insert_before_next_section(self):
        updated, _ = hold.transform(b'[main]\r\n# x\r\n[repo]\r\nx=y\r\n')
        self.assertNotIn(b'\n', updated.replace(b'\r\n', b''))
        self.assertLess(updated.index(b'excludepkgs='), updated.index(b'[repo]'))
    def test_missing_duplicate_ambiguous_main_refused(self):
        cases = (b'[repo]\nx=y\n', b'[main]\n[main]\n', b'[main]\nexcludepkgs=x\nexcludepkgs=y\n', b'[main]\nexcludepkgs=x # comment\n', b'[main]\nexcludepkgs=x\n y\n', b'[main]\nexclude=old\n')
        for data in cases:
            with self.subTest(data=data), self.assertRaises(hold.HoldError):
                hold.transform(data)
    def test_main_without_final_newline(self):
        updated, _ = hold.transform(b'[main]')
        self.assertTrue(updated.startswith(b'[main]\nexcludepkgs='))
    def test_apply_platform_gate(self):
        with patch.object(hold.platform, 'system', return_value='Darwin'):
            with self.assertRaises(hold.HoldError):hold.require_native_root()

class FileTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.config = self.root/'dnf.conf'
        self.original = b'# unchanged\n[main]\nexcludepkgs=old\n'
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        self.backups = self.root/'private'
    def tearDown(self):
        shutil.rmtree(self.root)
    def call(self, apply=False):
        return hold.manage(self.config, self.backups, apply, require_root=False)
    def test_default_no_writes(self):
        result = self.call()
        self.assertFalse(result['applied'])
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.backups.exists())
        self.assertEqual(len(result['exact_added_names']), 39)
        self.assertIn('restoration pending', result['mesa_status'])
    def test_apply_idempotence_and_metadata(self):
        before = self.config.stat()
        first = self.call(True)
        self.assertTrue(first['applied'])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(self.config.stat().st_uid, before.st_uid)
        self.assertEqual(self.config.stat().st_gid, before.st_gid)
        self.assertEqual(self.config.stat().st_mtime_ns, before.st_mtime_ns)
        receipt = Path(first['receipt'])
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(receipt.parent.stat().st_mode), 0o700)
        self.assertEqual((receipt.parent/'original.conf').read_bytes(), self.original)
        self.assertFalse(self.call(True)['applied'])
        self.assertEqual(len(list(self.backups.iterdir())), 1)
    def test_apply_rollback_and_rollback_noop(self):
        first = self.call(True)
        planned = hold.rollback(first['receipt'], require_root=False)
        self.assertFalse(planned['applied'])
        hold.rollback(first['receipt'], apply=True, require_root=False)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(hold.rollback(first['receipt'], apply=True, require_root=False)['action'], 'none')
    def test_rollback_refuses_later_edit(self):
        first = self.call(True)
        self.config.write_bytes(self.config.read_bytes()+b'# later setting\n')
        with self.assertRaisesRegex(hold.HoldError, 'newer settings'):
            hold.rollback(first['receipt'], apply=True, require_root=False)
    def test_symlink_and_hardlink_target_refused(self):
        real = self.root/'real'
        self.config.rename(real)
        self.config.symlink_to(real)
        with self.assertRaises(OSError):self.call(True)
        self.config.unlink()
        os.link(real,self.config)
        with self.assertRaises(hold.HoldError):self.call(True)
    def test_symlinked_parent_refused(self):
        directory = self.root/'real-dir';directory.mkdir()
        target = directory/'dnf.conf';target.write_bytes(self.original)
        link = self.root/'link';link.symlink_to(directory)
        with self.assertRaises(OSError):hold.manage(link/'dnf.conf', self.backups, require_root=False)
    def test_unsafe_mode_refused(self):
        for mode in (0o666, 0o4640):
            self.config.chmod(mode)
            with self.assertRaises(hold.HoldError):self.call(True)
    def test_postbackup_change_not_overwritten(self):
        real_write = hold.write_new
        def write(fd, name, data):
            real_write(fd, name, data)
            if name == 'receipt.json':self.config.write_bytes(self.original+b'# concurrent\n')
        with patch.object(hold, 'write_new', side_effect=write):
            with self.assertRaisesRegex(hold.HoldError, 'changed after backup'):self.call(True)
        self.assertEqual(self.config.read_bytes(), self.original+b'# concurrent\n')
    def test_backup_symlink_refused(self):
        real = self.root/'real-private';real.mkdir(mode=0o700)
        self.backups.symlink_to(real)
        with self.assertRaises(OSError):self.call(True)
    def test_corrupt_backup_refused(self):
        first = self.call(True)
        receipt = Path(first['receipt'])
        (receipt.parent/'original.conf').write_bytes(b'corrupt')
        with self.assertRaisesRegex(hold.HoldError, 'Backup hash'):hold.rollback(receipt,apply=True,require_root=False)
    def test_xattr_preserved_when_supported(self):
        if not hasattr(os, 'setxattr'):self.skipTest('xattrs unavailable')
        try:os.setxattr(self.config, 'user.caihong_test', b'keep')
        except OSError:self.skipTest('user xattrs unavailable on host filesystem')
        self.call(True)
        self.assertEqual(os.getxattr(self.config, 'user.caihong_test'), b'keep')

if __name__ == '__main__':unittest.main()
