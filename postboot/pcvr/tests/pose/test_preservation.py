"""Host-only patch, provenance and staging checks. No runtime or device access."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PCVR = HERE.parents[1]
BUILD = PCVR / "build"
sys.path.insert(0, str(BUILD))
import provenance
import fetch_vulkan_headers
import build_pose_capture_layer
import run_tests


def command(*arguments, cwd=None):
    return subprocess.run([str(arg) for arg in arguments], cwd=cwd, check=True,
                          capture_output=True, text=True)


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="caihong-pcvr-check-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_present_wait_exact_base_apply_and_reverse(self):
        package = PCVR / "patches/present-wait"
        manifest = json.loads((package / "manifest.json").read_text())
        for filename, key in [("alvr-v20.14.1-pr3357.patch", "minimal_patch_sha256"),
                              ("upstream-pr3357.patch", "upstream_patch_sha256")]:
            self.assertEqual(provenance.sha256((package / filename).read_bytes()), manifest[key])
        tree = self.root / "base"
        shutil.copytree(package / "base", tree)
        command(sys.executable, package / "verify_apply.py", tree)
        for record in manifest["files"]:
            data = (tree / record["path"]).read_bytes()
            self.assertEqual(provenance.sha256(data), record["base_sha256"])
            self.assertEqual(provenance.git_blob(data), record["base_git_blob"])
        command(sys.executable, package / "verify_apply.py", tree, "--apply")
        whitespace = subprocess.run(["git", "diff", "--no-index", "--check", str(package / "base"), str(tree)], capture_output=True, text=True)
        self.assertIn(whitespace.returncode, (0, 1))
        self.assertEqual(whitespace.stdout + whitespace.stderr, "")
        command("git", "apply", "--reverse", "--check", package / "alvr-v20.14.1-pr3357.patch", cwd=tree)
        for record in manifest["files"]:
            self.assertEqual(provenance.sha256((tree / record["path"]).read_bytes()), record["patched_sha256"])

    def test_present_wait_rejects_changed_base(self):
        package = PCVR / "patches/present-wait"
        tree = self.root / "bad-base"
        shutil.copytree(package / "base", tree)
        path = next(tree.rglob("*.cpp"))
        path.write_bytes(path.read_bytes() + b"\n")
        result = subprocess.run([sys.executable, str(package / "verify_apply.py"), str(tree), "--apply"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"not official unpatched", result.stderr)

    def test_headpose_exact_one_file_apply(self):
        package = PCVR / "patches/headpose"
        manifest = json.loads((package / "manifest.json").read_text())
        patch_path = package / "alvr-v20.14.1-exact-compositor-pose.patch"
        provenance.verify_patch(patch_path, manifest["patch_sha256"])
        self.assertEqual((patch_path.read_text()).count("--- a/"), 1)
        tree = self.root / "pose"
        shutil.copytree(package / "original", tree)
        self.assertEqual(provenance.sha256((tree / manifest["path"]).read_bytes()), manifest["base_sha256"])
        command("git", "apply", "--check", patch_path, cwd=tree)
        command("git", "apply", patch_path, cwd=tree)
        data = (tree / manifest["path"]).read_bytes()
        self.assertEqual(provenance.sha256(data), manifest["patched_sha256"])
        self.assertEqual(data, (package / "patched" / manifest["path"]).read_bytes())
        command("git", "apply", "--reverse", "--check", patch_path, cwd=tree)

    def test_source_closure_and_licenses(self):
        manifest = provenance.load_manifest("source-manifest.json")
        provenance.verify_tree(BUILD / "source", manifest["files"])
        self.assertEqual(len(manifest["cpp_sources"]), 16)
        actual = {str(path.relative_to(BUILD / "source")) for path in (BUILD / "source").rglob("*") if path.is_file()}
        self.assertEqual(actual, {record["path"] for record in manifest["files"]})
        licensing = json.loads((PCVR / "licenses/provenance.json").read_text())
        for record in licensing["licenses"]:
            data = (PCVR / "licenses" / record["path"]).read_bytes()
            self.assertEqual(provenance.sha256(data), record["sha256"])
            if "git_blob" in record:
                self.assertEqual(provenance.git_blob(data), record["git_blob"])

    def test_output_and_manifest_path_guards(self):
        with self.assertRaises(ValueError):
            provenance.external_path(PCVR / "build/generated")
        with self.assertRaises(ValueError):
            run_tests.external_path(PCVR / "tests/fixture")
        for bad in ["../escape", "/absolute", "x/../../escape"]:
            with self.assertRaises(ValueError):
                provenance.relative_path(bad)
        self.assertEqual(provenance.external_path(self.root), self.root.resolve())

    def test_manifest_detects_corruption(self):
        data = b"verified-header\n"
        record = {"path": "include/test.h", "size": len(data), "sha256": provenance.sha256(data),
                  "git_blob": provenance.git_blob(data)}
        provenance.verify_record(data, record)
        with self.assertRaises(ValueError):
            provenance.verify_record(data + b"x", record)
        with self.assertRaises(ValueError):
            provenance.verify_record(data, dict(record, git_blob="0" * 40))

    def fake_headers(self):
        data = b"// small deterministic header fixture\n"
        record = {"path": "include/vulkan/test.h", "size": len(data), "sha256": provenance.sha256(data),
                  "git_blob": provenance.git_blob(data)}
        manifest = {"repository": "test/headers", "commit": "1" * 40, "files": [record]}
        source = self.root / "header-source"
        path = source / record["path"]
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        return data, record, manifest, source

    def test_header_local_stage_and_verify(self):
        data, record, manifest, source = self.fake_headers()
        destination = self.root / "stage"
        with patch.object(fetch_vulkan_headers, "load_manifest", return_value=manifest), contextlib.redirect_stdout(io.StringIO()):
            fetch_vulkan_headers.stage(destination, source=source)
            fetch_vulkan_headers.stage(destination, verify_only=True)
            (destination / record["path"]).write_bytes(data + b"corrupt")
            with self.assertRaises(ValueError):
                fetch_vulkan_headers.stage(destination, source=source)

    def test_header_authenticated_fetch_checks_blob_metadata(self):
        data, record, manifest, _ = self.fake_headers()
        response = {"type": "file", "encoding": "base64", "sha": record["git_blob"],
                    "path": record["path"], "content": base64.b64encode(data).decode()}
        with patch.object(fetch_vulkan_headers, "load_manifest", return_value=manifest), \
                patch.object(fetch_vulkan_headers.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(response))) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            fetch_vulkan_headers.stage(self.root / "download")
        self.assertEqual(run.call_args_list[0].args[0], ["gh", "auth", "status", "--hostname", "github.com"])
        self.assertIn("?ref=" + manifest["commit"], run.call_args_list[1].args[0][-1])
        response["sha"] = "0" * 40
        with patch.object(fetch_vulkan_headers, "load_manifest", return_value=manifest), \
                patch.object(fetch_vulkan_headers.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(response))):
            with self.assertRaises(ValueError):
                fetch_vulkan_headers.stage(self.root / "bad-download")

    def test_header_symlink_escape_rejected(self):
        _, record, manifest, source = self.fake_headers()
        destination = self.root / "symlink-stage"
        destination.mkdir()
        (destination / "include").symlink_to(source / "include", target_is_directory=True)
        with patch.object(fetch_vulkan_headers, "load_manifest", return_value=manifest):
            with self.assertRaises(ValueError):
                fetch_vulkan_headers.stage(destination, source=source)

    def test_external_replay_fixture_required_and_hash_checked(self):
        metadata = json.loads((HERE / "replay-metadata.json").read_text())
        self.assertFalse(metadata["fixture_in_repository"])
        self.assertEqual(metadata["fixture_bytes"], 22048)
        fixture = self.root / "invalid-frame"
        fixture.write_bytes(b"x" * metadata["fixture_bytes"])
        with self.assertRaises(ValueError):
            run_tests.verify_fixture(fixture)
        self.assertFalse(list(PCVR.rglob("update-frame.bin")))

    def test_build_stage_and_compile_plan(self):
        _, _, manifest, headers = self.fake_headers()
        real_loader = build_pose_capture_layer.load_manifest
        with patch.object(build_pose_capture_layer, "load_manifest", side_effect=lambda name: manifest if name == "vulkan-headers-manifest.json" else real_loader(name)):
            source_manifest, layer, server, output, shim, exports = build_pose_capture_layer.prepare(
                self.root / "build", headers, "/var/lib/alvr/session.json")
        commands, library = build_pose_capture_layer.commands(layer, server, output, shim, exports,
            headers, ["g++"], source_manifest["cpp_sources"])
        self.assertEqual(len(commands), 18)
        self.assertIn("-Wl,--no-undefined", commands[-1])
        self.assertIn("-lunwind", commands[-1])
        self.assertIn("/var/lib/alvr/session.json", shim.read_text())
        self.assertIn("exact-build-hmd0", (layer / "util/pose.cpp").read_text())
        self.assertFalse(library.exists())
        self.assertEqual(exports.read_text(), "{global: ALVR_Negotiate; local:*;};\n")

    def test_main_comm_template_patch_and_build_stage(self):
        package = PCVR / "patches/main-comm"
        manifest = json.loads((package / "manifest.json").read_text())
        for record in manifest["files"]:
            self.assertEqual(provenance.sha256((package / record["path"]).read_bytes()), record["sha256"])
        tree = self.root / "main-comm-patch"
        tree.mkdir()
        shutil.copyfile(package / "ALVR_Negotiate.before.cpp.in", tree / "ALVR_Negotiate.cpp.in")
        command("git", "apply", "--check", package / "main-comm-shim.patch", cwd=tree)
        command("git", "apply", package / "main-comm-shim.patch", cwd=tree)
        self.assertEqual((tree / "ALVR_Negotiate.cpp.in").read_bytes(), (package / "ALVR_Negotiate.cpp.in").read_bytes())
        self.assertEqual((tree / "compositor_main_comm.h").read_bytes(), (package / "compositor_main_comm.h").read_bytes())
        command("git", "apply", "--reverse", "--check", package / "main-comm-shim.patch", cwd=tree)
        _, _, header_manifest, headers = self.fake_headers()
        real_loader = build_pose_capture_layer.load_manifest
        with patch.object(build_pose_capture_layer, "load_manifest", side_effect=lambda name: header_manifest if name == "vulkan-headers-manifest.json" else real_loader(name)):
            _, _, _, output, shim, _ = build_pose_capture_layer.prepare(
                self.root / "main-comm-build", headers, "/var/lib/alvr/session.json", main_comm=True)
        self.assertIn('#include "compositor_main_comm.h"', shim.read_text())
        self.assertNotIn("@SESSION_PATH@", shim.read_text())
        self.assertEqual((output / "compositor_main_comm.h").read_bytes(), (package / "compositor_main_comm.h").read_bytes())

    def test_preserved_paths_contain_only_small_text_files(self):
        roots = [PCVR / "patches", PCVR / "tests/pose", PCVR / "build", PCVR / "licenses"]
        for root in roots:
            for path in root.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    self.assertLess(path.stat().st_size, 100000, str(path))
                    self.assertNotIn(path.suffix, [".so", ".o", ".bin", ".core", ".pyc"], str(path))
                    self.assertNotIn(b"\0", path.read_bytes(), str(path))
                    self.assertNotIn(("/" + "Users/"), path.read_text(), str(path))
                    self.assertNotIn(("/var/" + "home/"), path.read_text(), str(path))


if __name__ == "__main__":
    unittest.main()
