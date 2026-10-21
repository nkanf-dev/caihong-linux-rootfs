import importlib.util
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import unittest
import contextlib
import io
import tempfile
import json
import os

spec = importlib.util.spec_from_file_location("stage", Path(__file__).with_name("stage_compositor_turnip_probe.py"))
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

class CandidateTests(unittest.TestCase):
    def test_preserves_repeated_keys_and_all_other_bytes(self):
        raw = b'{"Config":{"Env":"LD_PRELOAD=old","HostEnv":"XDG_RUNTIME_DIR=/tmp/old","Env":"ALVR_SESSION_JSON=/tmp/session"},"ThunksDB":{"Vulkan":0,"drm":0}}\n'
        got = stage.generate(raw, "flushall")
        expected = raw.replace(b'},"ThunksDB"', b',"HostEnv":"TU_DEBUG=flushall"},"ThunksDB"')
        self.assertEqual(got, expected)
    def test_empty_config(self):
        self.assertEqual(stage.generate(b'{"Config": {  }}', "nomultipos"), b'{"Config": {  "HostEnv":"TU_DEBUG=nomultipos"}}')
    def test_refuses_existing_env(self):
        with self.assertRaisesRegex(ValueError, "Existing TU_DEBUG"):
            stage.generate(b'{"Config":{"Env":"TU_DEBUG=sysmem"}}', "flushall")
    def test_refuses_existing_hostenv_array(self):
        with self.assertRaisesRegex(ValueError, "Existing TU_DEBUG"):
            stage.generate(b'{"Config":{"HostEnv":["A=B","TU_DEBUG=nolrz"]}}', "flushall")
    def test_refuses_duplicate_config(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            stage.generate(b'{"Config":{},"Config":{}}', "flushall")
    def test_refuses_missing_config(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            stage.generate(b'{"X":{}}', "flushall")
    def test_handles_strings_with_braces(self):
        raw = b'{"Other":"}Config{","Config":{"Env":"STR=\\\"}hello"},"Tail":2}'
        got = stage.generate(raw, "flushall")
        self.assertIn(b'TU_DEBUG=flushall', got)
    def test_refuses_unknown_mode(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            stage.generate(b'{"Config":{}}', "all")

class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "vrcompositor.real.json"
        self.source.write_bytes(b'{"Config":{"HostEnv":"KEEP=1","Env":"A=B","Env":"C=D"},"ThunksDB":{"Vulkan":0,"drm":0}}')
        self.output = self.root / "vrcompositor.real.flushall.candidate.json"
    def run_main(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return stage.main([str(x) for x in args])
    def test_creates_candidate_and_manifest_but_preserves_input(self):
        before = self.source.read_bytes()
        self.run_main([self.source, self.output])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.output.read_bytes(), stage.generate(before, "flushall"))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        manifest = json.loads(self.output.with_name(self.output.name + ".manifest.json").read_text())
        self.assertEqual(manifest["input_sha256"], stage.digest(before))
        self.assertFalse(manifest["live_changes"])
    def test_refuses_overwrite(self):
        self.output.write_text("keep")
        with self.assertRaises(SystemExit):
            self.run_main([self.source, self.output])
        self.assertEqual(self.output.read_text(), "keep")
    def test_refuses_same_path(self):
        before = self.source.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_main([self.source, self.source])
        self.assertEqual(self.source.read_bytes(), before)
    def test_refuses_output_symlink(self):
        target = self.root / "target.candidate.json"
        self.output.symlink_to(target)
        with self.assertRaises(SystemExit):
            self.run_main([self.source, self.output])
        self.assertFalse(target.exists())
    def test_refuses_live_profile_filename(self):
        dest = self.root / "elsewhere" / "vrcompositor.real.json"
        dest.parent.mkdir()
        with self.assertRaises(SystemExit):
            self.run_main([self.source, dest])
        self.assertFalse(dest.exists())
    def assert_appconfig_refused(self, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = self.source.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_main([self.source, dest])
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_name(dest.name + ".manifest.json").exists())
        self.assertEqual(self.source.read_bytes(), before)
    def test_refuses_appconfig_destination(self):
        self.assert_appconfig_refused(self.root / "fex-emu" / "AppConfig" / self.output.name)
    def test_refuses_legacy_dot_fex_appconfig(self):
        self.assert_appconfig_refused(self.root / ".fex-emu" / "AppConfig" / self.output.name)
    def test_refuses_modern_config_fex_appconfig(self):
        self.assert_appconfig_refused(self.root / ".config" / "fex-emu" / "AppConfig" / self.output.name)
    def test_refuses_case_variants(self):
        for directory in ("FEX-EMU", ".Fex-Emu"):
            with self.subTest(directory=directory):
                self.assert_appconfig_refused(self.root / directory / "appCONFIG" / self.output.name)
    def test_refuses_appconfig_under_arbitrary_override_root(self):
        self.assert_appconfig_refused(self.root / "custom-config-location" / "AppConfig" / self.output.name)
    def test_refuses_resolved_appconfig_alias(self):
        actual = self.root / ".fex-emu" / "AppConfig"
        actual.mkdir(parents=True)
        alias = self.root / "innocent-export"
        alias.symlink_to(actual, target_is_directory=True)
        self.assert_appconfig_refused(alias / self.output.name)
    def test_refuses_lexical_appconfig_alias_to_export(self):
        actual = self.root / "private-export"
        actual.mkdir()
        parent = self.root / ".FEX-EMU"
        parent.mkdir()
        alias = parent / "APPconfig"
        alias.symlink_to(actual, target_is_directory=True)
        self.assert_appconfig_refused(alias / self.output.name)
    def test_manifest_is_private_at_creation(self):
        from unittest.mock import patch
        calls = []
        original_open = stage.os.open
        def record_open(path, flags, mode=0o777, **kwargs):
            calls.append((Path(path), mode))
            return original_open(path, flags, mode, **kwargs)
        with patch.object(stage.os, "open", side_effect=record_open):
            self.run_main([self.source, self.output])
        manifest = self.output.with_name(self.output.name + ".manifest.json")
        self.assertEqual([mode for path, mode in calls if path.resolve() == manifest.resolve()], [0o600])
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
    def test_manifest_write_failure_cleans_new_artifacts(self):
        from unittest.mock import patch
        before = self.source.read_bytes()
        with patch.object(stage.json, "dump", side_effect=OSError("synthetic write failure")):
            with self.assertRaisesRegex(OSError, "synthetic"):
                self.run_main([self.source, self.output])
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name + ".manifest.json").exists())
        self.assertEqual(self.source.read_bytes(), before)
    def test_refuses_existing_manifest(self):
        manifest = self.output.with_name(self.output.name + ".manifest.json")
        manifest.write_text("keep")
        with self.assertRaises(SystemExit):
            self.run_main([self.source, self.output])
        self.assertFalse(self.output.exists())
        self.assertEqual(manifest.read_text(), "keep")

if __name__ == "__main__":
    unittest.main()
