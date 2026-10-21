import copy
import importlib.util
import json
import os
import shutil
import stat
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location('baseline', HERE/'assert_custom_package_baseline.py')
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)
POLICY = ROOT/'rootfs/armada/etc/dnf/dnf.conf'
DIGEST = 'sha256:' + 'a'*64

class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.names = baseline.protected_names(POLICY)
        self.rows = {name: [{'name': name, 'epoch': '0', 'version': '1.0', 'release': '1.fc44.armada', 'arch': 'aarch64', 'vendor': 'Armada', 'source_rpm': name+'-1.0-1.fc44.armada.src.rpm', 'payload_digest': 'b'*64}] for name in self.names}
        self.saved = baseline.capture(self.rows, self.names, DIGEST)
    def test_canonical_39_exact_names_and_original_baseline_pass(self):
        self.assertEqual(len(self.names), 39)
        baseline.compare(self.saved, self.rows, self.names, DIGEST)
    def test_added_or_updated_ordinary_dependencies_are_allowed(self):
        rows = copy.deepcopy(self.rows)
        rows['systemd'] = [{'version': 'new security update'}]
        baseline.compare(self.saved, rows, self.names, DIGEST)
    def test_dnf38_six_generic_mesa_replacements_fail(self):
        rows = copy.deepcopy(self.rows)
        names = [name for name in self.names if name.startswith('mesa-')]
        self.assertEqual(len(names), 6)
        for name in names:rows[name][0].update(release='1.fc44', vendor='Fedora Project')
        with self.assertRaises(baseline.BaselineError) as error:baseline.compare(self.saved, rows, self.names, DIGEST)
        for name in names:self.assertIn(name+':',str(error.exception))
        self.assertIn('isolated camera builder',str(error.exception))
    def test_dnf40_three_terra_replacements_fail(self):
        rows = copy.deepcopy(self.rows)
        for name in ('gamescope-session','inputplumber','steamos-manager'):rows[name][0].update(release='2.fc44', vendor='Terra')
        with self.assertRaises(baseline.BaselineError) as error:baseline.compare(self.saved, rows, self.names, DIGEST)
        for name in ('gamescope-session','inputplumber','steamos-manager'):self.assertIn(name+':',str(error.exception))
    def test_generic_initial_baseline_is_rejected(self):
        self.rows['mesa-libEGL'][0].update(release='1.fc44',vendor='Fedora Project')
        with self.assertRaisesRegex(baseline.BaselineError,'not an Armada'):baseline.capture(self.rows,self.names,DIGEST)
    def test_custom_release_without_vendor_is_accepted(self):
        self.rows['armada-aurora'][0]['vendor']='(none)'
        baseline.capture(self.rows,self.names,DIGEST)
    def test_missing_and_duplicate_protected_packages_fail(self):
        for replacement in ([], self.rows['inputplumber']*2):
            rows=copy.deepcopy(self.rows);rows['inputplumber']=replacement
            with self.assertRaisesRegex(baseline.BaselineError,'inputplumber'):baseline.compare(self.saved,rows,self.names,DIGEST)
    def test_full_epoch_version_arch_vendor_source_payload_identity_checked(self):
        for field in baseline.FIELDS[1:]:
            with self.subTest(field=field):
                rows=copy.deepcopy(self.rows);rows['steamos-manager'][0][field]='changed'
                with self.assertRaisesRegex(baseline.BaselineError,field+'='):baseline.compare(self.saved,rows,self.names,DIGEST)
    def test_image_digest_and_policy_set_change_fail(self):
        with self.assertRaisesRegex(baseline.BaselineError,'digest'):baseline.compare(self.saved,self.rows,self.names,'sha256:'+'c'*64)
        altered=copy.deepcopy(self.saved);altered['protected_names'].pop()
        with self.assertRaisesRegex(baseline.BaselineError,'package set'):baseline.compare(altered,self.rows,self.names,DIGEST)
    def test_corrupt_generic_saved_baseline_does_not_waive_check(self):
        saved=copy.deepcopy(self.saved);saved['packages']['inputplumber'].update(release='1.fc44',vendor='Terra')
        with self.assertRaises(baseline.BaselineError):baseline.compare(saved,self.rows,self.names,DIGEST)
    def test_missing_payload_digest_fails(self):
        self.rows['kwin'][0]['payload_digest']='(none)'
        with self.assertRaisesRegex(baseline.BaselineError,'payload identity'):baseline.capture(self.rows,self.names,DIGEST)
    def test_policy_token_drift_and_wildcard_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'dnf.conf'
            for names in (self.names[:-1], self.names[:-1]+('NetworkManager*',)):
                path.write_text('[main]\nexcludepkgs='+','.join(names)+'\n')
                with self.assertRaises(baseline.BaselineError):baseline.protected_names(path)
    def test_native_rpm_query_is_readonly_and_offline_root_bounded(self):
        calls=[]
        row=self.rows['inputplumber'][0]
        text='\t'.join(row[field]for field in baseline.FIELDS)+'\n'
        def run(args,**kwargs):calls.append(args);return subprocess.CompletedProcess(args,0,text,'')
        with tempfile.TemporaryDirectory() as directory:
            parsed=baseline.query_root(directory,run)
        self.assertEqual(calls[0][2:5],['/usr/bin/rpm','-qa','--qf'])
        self.assertEqual(parsed['inputplumber'],[row])
        with self.assertRaises(baseline.BaselineError):baseline.query_root('/',run)
    def test_epoch_none_normalized_and_malformed_rows_rejected(self):
        row=self.rows['kwin'][0].copy();row['epoch']='(none)'
        parsed=baseline.parse_rows('\t'.join(row[field]for field in baseline.FIELDS)+'\n')
        self.assertEqual(parsed['kwin'][0]['epoch'],'0')
        with self.assertRaises(baseline.BaselineError):baseline.parse_rows('wrong fields')
    def test_packager_gate_order(self):
        text=(ROOT/'scripts/package-armada-rootfs.sh').read_text()
        capture=text.index('custom_package_baseline capture')
        install=text.index('/usr/bin/dnf5 -y install')
        first_check=text.index('custom_package_baseline check',install)
        removal=text.index('/usr/bin/dnf5 -y remove')
        after_remove=text.index('custom_package_baseline check',removal)
        final_check=text.rindex('custom_package_baseline check')
        artifact=text.index('echo "creating $output"')
        self.assertTrue(capture<install<first_check<removal<after_remove<=final_check<artifact)


class PolicyMergeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp()).resolve()
        self.config = self.directory/'etc/dnf/dnf.conf'
        self.config.parent.mkdir(parents=True)
        self.original = b'# upstream default\r\n[main]\r\ninstallonly_limit=7\r\nexcludepkgs=prior-pin\r\n# keep comment\r\n[other]\r\nvalue=unchanged\r\n'
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        self.names = baseline.protected_names(POLICY)
        self.lock = baseline.lock_module()
    def tearDown(self):
        shutil.rmtree(self.directory)
    def merge(self):
        # Simulate only target file ownership on this unprivileged host fixture.
        original_read = self.lock.read_file
        def read(fd, name, require_root=True):
            data, metadata, identity = original_read(fd,name,require_root=False)
            return data, metadata, identity
        with patch.object(baseline,'lock_module',return_value=self.lock), patch.object(self.lock,'read_file',side_effect=read):
            return baseline.merge_policy(self.directory,self.names)
    def test_merge_preserves_defaults_prior_holds_comments_crlf_and_metadata(self):
        before=self.config.stat()
        self.assertTrue(self.merge())
        data=self.config.read_bytes()
        self.assertIn(b'installonly_limit=7\r\n',data)
        self.assertIn(b'excludepkgs=prior-pin,',data)
        self.assertTrue(data.endswith(b'# keep comment\r\n[other]\r\nvalue=unchanged\r\n'))
        self.assertNotIn(b'\n',data.replace(b'\r\n',b''))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode),0o640)
        self.assertEqual((self.config.stat().st_uid,self.config.stat().st_gid),(before.st_uid,before.st_gid))
        self.assertEqual(self.config.stat().st_mtime_ns,before.st_mtime_ns)
        self.assertFalse(self.merge())
    def test_merge_target_symlink_rejected(self):
        real=self.config.with_name('actual.conf');self.config.rename(real);self.config.symlink_to(real)
        with self.assertRaises(OSError):self.merge()
        self.assertEqual(real.read_bytes(),self.original)
    def test_merge_parent_symlink_rejected(self):
        real=self.directory/'real-dnf';self.config.parent.rename(real);self.config.parent.symlink_to(real)
        with self.assertRaises(OSError):self.merge()
    def test_merge_requires_real_target_root_owner(self):
        lock=self.lock
        real_fstat=os.fstat
        def fstat(fd):
            info=real_fstat(fd)
            if stat.S_ISREG(info.st_mode):
                values=list(info);values[4]=12345
                return os.stat_result(values)
            return info
        with patch.object(baseline,'lock_module',return_value=lock),patch.object(lock.os,'fstat',side_effect=fstat):
            with self.assertRaisesRegex(baseline.BaselineError,'root-owned'):baseline.merge_policy(self.directory,self.names)
    def test_shared_writer_xattr_metadata_roundtrip_with_mock(self):
        # The Mac harness lacks os xattr calls; assert writer passes exact bytes.
        captured=[]
        def listxattr(fd):return ['security.selinux']
        def getxattr(fd,name):return b'system_u:object_r:etc_t:s0'
        def setxattr(fd,name,value):captured.append((name,value))
        with patch.object(self.lock.os,'listxattr',listxattr,create=True),patch.object(self.lock.os,'getxattr',getxattr,create=True),patch.object(self.lock.os,'setxattr',setxattr,create=True):
            self.merge()
        self.assertEqual(captured,[('security.selinux',b'system_u:object_r:etc_t:s0')])
    def test_overlay_excludes_only_dnf_config_and_merges_afterward(self):
        text=(ROOT/'scripts/package-armada-rootfs.sh').read_text()
        exclude=text.index("--exclude='/etc/dnf/dnf.conf'")
        overlay=text.index('"$project_dir/rootfs/armada/" "$rootfs/"',exclude)
        merge=text.index('custom_package_baseline merge-policy',overlay)
        self.assertLess(exclude,overlay)
        self.assertLess(overlay,merge)

if __name__=='__main__':unittest.main()
