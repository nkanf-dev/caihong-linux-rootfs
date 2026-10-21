import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("armada_build", ROOT / "build.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildConfigTest(unittest.TestCase):
    def config(self):
        return json.loads((ROOT / "config/deployment.example.json").read_text())

    def test_exact_paths(self):
        module.validate_paths({"bootPath": "/dev/block/by-name/boot_b", "linuxPath": "/dev/block/by-name/linux"})

    def test_wrong_boot_paths(self):
        for path in ("/dev/block/by-name/boot_a", "/dev/block/by-name/linux",
                     "/dev/block/bootdevice/by-name/boot_b", "/dev/block/sde17"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.validate_paths({"bootPath": path, "linuxPath": "/dev/block/by-name/linux"})

    def test_wrong_linux_path(self):
        with self.assertRaises(ValueError):
            module.validate_paths({"bootPath": "/dev/block/by-name/boot_b", "linuxPath": "/dev/block/by-name/userdata"})

    def test_example_is_disabled(self):
        c = self.config()
        module.validate_config(c)
        self.assertFalse(c["deploymentReady"])
        self.assertEqual(c["imageBytes"], 0)
        self.assertEqual(c["imageSha256"], "")
        self.assertTrue(c["model"].startswith("REPLACE_"))
        self.assertTrue(c["device"].startswith("REPLACE_"))

    def test_deployment_needs_verified_identity_and_image(self):
        c = self.config()
        c["deploymentReady"] = True
        with self.assertRaises(ValueError):
            module.validate_config(c)
        c.update(model="TEST_MODEL", device="TEST_DEVICE", imageBytes=3,
                 imageSha256="a" * 64, sourceRun="123", sourceCommit="b" * 40)
        module.validate_config(c)
        for key, value in (("imageBytes", 0), ("imageSha256", "G" * 64),
                           ("model", "REPLACE_WITH_VERIFIED_MODEL"), ("device", "")):
            broken = dict(c, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_config(broken)

    def test_mapping_size_and_interface_are_fixed(self):
        for key, value in (("androidSlot", 1), ("linuxSlot", 0),
                           ("linuxBytes", 1024), ("linuxPartlabel", "userdata"),
                           ("aidlVersion", 2), ("aidlHash", "f" * 40),
                           ("imageBytes", -1), ("imageBytes", 1024 ** 3 + 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_config(dict(self.config(), **{key: value}))

    def test_types_and_unknown_fields_are_rejected(self):
        for changes in ({"deploymentReady": "false"}, {"androidSlot": False},
                        {"imageBytes": 1.0}, {"pin": "REPLACE_LOCALLY"}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValueError):
                module.validate_config(dict(self.config(), **changes))

    def test_render_matches_sanitized_source(self):
        expected = (ROOT / "src/cn/armada/dualswitch/TargetConfig.java").read_text()
        self.assertEqual(module.render_config(self.config()), expected)

    def test_generate_writes_only_requested_destination(self):
        source = ROOT / "src/cn/armada/dualswitch/TargetConfig.java"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory(prefix=".source-test-", dir=ROOT) as temp:
            destination = pathlib.Path(temp) / "generated/TargetConfig.java"
            result = module.generate_config(ROOT / "config/deployment.example.json", destination)
            self.assertEqual(destination.read_text(), module.render_config(result))
        self.assertEqual(source.read_bytes(), before)

    def test_jdk_can_use_path_without_host_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(module.shutil, "which", side_effect=lambda n: "/test-jdk/bin/" + n):
            self.assertEqual(module.java_tool("javac", None), pathlib.Path("/test-jdk/bin/javac"))

    def test_sdk_needs_explicit_configuration(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            module.sdk_root(None)


if __name__ == "__main__":
    unittest.main()
