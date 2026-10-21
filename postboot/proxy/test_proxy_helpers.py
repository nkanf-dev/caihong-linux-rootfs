import importlib.util
import json
import os
from pathlib import Path
import tempfile
import contextlib
import io
import types
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


local = load("deckyclash_local", "deckyclash-local.py")
hk = load("hk_controller", "hk-controller.py")


class LocalTests(unittest.TestCase):
    def test_merge_retains_unrelated_private_values(self):
        target = {"tun-override": {"route-exclude-address": ["REPLACE_LOCAL_EXCLUSION"]},
                  "always-override": {"profile": {"private-existing-key": True}}, "keep": 12}
        local.merge(target, {"tun-override": {"auto-redirect": False},
                             "always-override": {"profile": {"store-selected": True}}})
        self.assertEqual(target["tun-override"]["route-exclude-address"], ["REPLACE_LOCAL_EXCLUSION"])
        self.assertTrue(target["always-override"]["profile"]["private-existing-key"])
        self.assertTrue(target["always-override"]["profile"]["store-selected"])
        self.assertFalse(target["tun-override"]["auto-redirect"])
        self.assertEqual(target["keep"], 12)

    def test_atomic_write_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            local.atomic_write(path, "{}\n")
            local.private_file(path)
            self.assertEqual(path.read_text(), "{}\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_configure_autostart_restore_end_to_end_with_fake_yaml(self):
        # JSON is a YAML subset. A fake parser keeps this test independent of vendored packages.
        class FakeYaml:
            def load(self, text):
                return json.loads(text)

            def dump(self, value, stream):
                json.dump(value, stream)

        module = types.ModuleType("ruamel.yaml")
        module.YAML = FakeYaml
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "homebrew"
            settings = base / local.FILES[0]
            override = base / local.FILES[1]
            settings.parent.mkdir(parents=True)
            override.parent.mkdir(parents=True)
            original_settings = {"secret": "x" * 24, "autostart": True,
                                 "subscriptions": {"REPLACE_LOCAL_ID": {"keep": True}}}
            original_override = {"tun-override": {"route-exclude-address": ["REPLACE_LOCAL_EXCLUSION"]}}
            for path, value in ((settings, original_settings), (override, original_override)):
                path.write_text(json.dumps(value))
                path.chmod(0o600)
            backup = Path(directory) / "rollback"
            patch_text = json.dumps({"tun-override": {"auto-redirect": False},
                                     "always-override": {"mode": "global"}})
            original_read = Path.read_text
            def read(path, *args, **kwargs):
                return patch_text if path.name == "caihong-policy-tun.yaml" else original_read(path, *args, **kwargs)
            def invoke(action):
                with patch("sys.argv", ["deckyclash-local.py", action, "--homebrew", str(base),
                                        "--backup-dir", str(backup)]), contextlib.redirect_stdout(io.StringIO()):
                    local.main()
            import sys
            old_path = sys.path[:]
            try:
                with patch.dict(sys.modules, {"ruamel": types.ModuleType("ruamel"), "ruamel.yaml": module}), \
                     patch.object(Path, "read_text", read):
                    invoke("configure")
                    changed = json.loads(settings.read_text())
                    self.assertFalse(changed["autostart"])
                    self.assertFalse(changed["skip_steam_download"])
                    self.assertEqual(changed["subscriptions"], original_settings["subscriptions"])
                    self.assertEqual(changed["secret"], original_settings["secret"])
                    patched = json.loads(override.read_text())
                    self.assertFalse(patched["tun-override"]["auto-redirect"])
                    self.assertEqual(patched["tun-override"]["route-exclude-address"], ["REPLACE_LOCAL_EXCLUSION"])
                    self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
                    invoke("enable-autostart")
                    self.assertTrue(json.loads(settings.read_text())["autostart"])
                    invoke("disable-autostart")
                    self.assertFalse(json.loads(settings.read_text())["autostart"])
                    invoke("restore")
            finally:
                sys.path[:] = old_path
            self.assertEqual(json.loads(settings.read_text()), original_settings)
            self.assertEqual(json.loads(override.read_text()), original_override)

    def test_private_file_refuses_loose_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                local.private_file(path)
            path.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                local.private_file(link)


class ControllerTests(unittest.TestCase):
    def settings(self):
        return {"controller_port": 9090, "secret": "x" * 24, "allow_remote_access": False}

    def test_refuses_remote_access_placeholder_and_boolean_port(self):
        for change in ({"allow_remote_access": True}, {"secret": "REPLACE_CONTROLLER_SECRET"},
                       {"controller_port": True}, {"controller_port": 65536}):
            settings = self.settings()
            settings.update(change)
            with self.assertRaises(ValueError):
                hk.Controller(settings)

    def test_loopback_auth_proxy_bypass_and_redirect_refusal(self):
        with patch.object(hk.urllib.request, "build_opener") as build:
            api = hk.Controller(self.settings())
            self.assertEqual(api.base, "http://127.0.0.1:9090")
            self.assertEqual(build.call_args.args[0].proxies, {})
            redirect = build.call_args.args[1]
            self.assertIsNone(redirect.redirect_request(None, None, 302, "", {}, "http://example.invalid"))

    def test_request_uses_json_and_does_not_print_response(self):
        with patch.object(hk.urllib.request, "build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"now":"unit-test-only"}'
            api = hk.Controller(self.settings())
            result = api.request("/proxies/GLOBAL", "PUT", {"name": "unit-test-only"})
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:9090/proxies/GLOBAL")
            self.assertEqual(request.method, "PUT")
            self.assertEqual(json.loads(request.data), {"name": "unit-test-only"})
            self.assertEqual(request.get_header("Authorization"), "Bearer " + "x" * 24)
            self.assertEqual(result, {"now": "unit-test-only"})

    def test_private_selection_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            path.write_text('{"node":"REPLACE_HK_NODE_NAME"}')
            path.chmod(0o600)
            self.assertEqual(hk.private_json(path), {"node": "REPLACE_HK_NODE_NAME"})
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                hk.private_json(path)


if __name__ == "__main__":
    unittest.main()
