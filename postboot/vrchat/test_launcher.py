#!/usr/bin/env python3
"""Host-only launcher tests. execv is mocked. No Steam or device access."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("private_vrchat_route", HERE / "launch_vrchat_known_route.py")
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".launcher-test-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.uid = os.getuid() or 1234
        self.private = self.home / ".local/share" / route.PRIVATE_NAME
        self.old = self.home / ".local/share/Steam/steamapps/common/FEX-Emu/fex-compat-tool"
        self.new = self.private / "fex-compat-tool"
        self.armada = self.home / "armada-game-launch"
        self.prefix = self.home / ".local/share/cvrc-x64"
        self.prefix.mkdir(parents=True)
        self.state = self.home / ".local/state/caihong-vrchat-logs/x64-known-route"
        self.state.mkdir(mode=0o700, parents=True)
        for executable in (self.old, self.new, self.armada):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("fixture\n")
            executable.chmod(0o700)
        self.old_bytes = self.old.read_bytes()
        self.args = ["runtime-entry", "--", str(self.old), "waitforexitandrun", "launch.exe", "--no-vr"]
        self.env = {"HOME": str(self.home), "SteamAppId": "438100",
                    "STEAM_COMPAT_DATA_PATH": str(self.prefix),
                    "XDG_RUNTIME_DIR": f"/run/user/{self.uid}"}
        self.addCleanup(patch.stopall)
        patch.object(route.Path, "home", return_value=self.home).start()
        patch.object(route.os, "getuid", return_value=self.uid).start()
        patch.object(route, "ARMADA_LAUNCHER", str(self.armada)).start()
        patch.dict(route.os.environ, self.env, clear=True).start()
        # No runtime filesystem operations occur in these mocked launch tests.
        self.owner = patch.object(route, "owner_directory").start()
        self.execv = patch.object(route.os, "execv").start()

    def test_exact_private_substitution_preserves_chain(self):
        original = list(self.args)
        route.launch(self.args)
        expected = list(original)
        expected[2] = str(self.new)
        self.execv.assert_called_once_with(str(self.armada), [str(self.armada)] + expected)
        self.assertEqual(self.args, original)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual(list(self.prefix.iterdir()), [])

    def test_private_environment_and_no_argument_logging(self):
        os.environ.update(PROTON_LOG="1", PROTON_LOG_DIR="not-used", STEAM_COMPAT_TOOL_PATHS="/first::/last")
        route.launch(self.args + ["unrecorded-synthetic-value"])
        self.assertNotIn("PROTON_LOG", os.environ)
        self.assertNotIn("PROTON_LOG_DIR", os.environ)
        self.assertEqual(os.environ["STEAM_COMPAT_TOOL_PATHS"], "/first:/last:" + str(self.private))
        self.assertEqual(os.environ["FEX_APP_DATA_LOCATION"], f"/run/user/{self.uid}/cvrc-fex/data/")
        self.assertEqual(os.environ["FEX_APP_CACHE_LOCATION"], str(self.prefix / "fex-cache") + "/")
        path = self.state / "launch-routing.json"
        record = json.loads(path.read_text())
        self.assertNotIn("unrecorded-synthetic-value", path.read_text())
        self.assertNotIn("argv", record)
        self.assertFalse(record["stock_tool_changed"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_tool_path_is_not_duplicated(self):
        os.environ["STEAM_COMPAT_TOOL_PATHS"] = str(self.private)
        route.launch(self.args)
        self.assertEqual(os.environ["STEAM_COMPAT_TOOL_PATHS"], str(self.private))

    def test_runtime_fallback_uses_current_uid(self):
        os.environ.pop("XDG_RUNTIME_DIR")
        route.launch(self.args)
        self.assertEqual(os.environ["FEX_APP_DATA_LOCATION"], f"/run/user/{self.uid}/cvrc-fex/data/")

    def test_explicit_short_runtime_is_used(self):
        os.environ["XDG_RUNTIME_DIR"] = "/owner-run"
        route.launch(self.args)
        self.assertEqual(os.environ["FEX_APP_DATA_LOCATION"], "/owner-run/cvrc-fex/data/")

    def test_missing_duplicate_and_near_match_wrappers_rejected(self):
        for args in ([], self.args + [str(self.old)], [str(self.old) + ".other"]):
            with self.subTest(args_count=len(args)), self.assertRaisesRegex(RuntimeError, "exactly one"):
                route.launch(args)
        self.execv.assert_not_called()

    def test_wrong_app_and_prefix_rejected(self):
        for key, value in (("SteamAppId", "999999"), ("STEAM_COMPAT_DATA_PATH", str(self.home / "wrong"))):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaises(RuntimeError):
                    route.launch(self.args)
        self.execv.assert_not_called()

    def test_experimental_options_rejected(self):
        for key in route.EXPERIMENTAL:
            with self.subTest(key=key), patch.dict(os.environ, {key: "1"}):
                with self.assertRaisesRegex(RuntimeError, "experimental FEX"):
                    route.launch(self.args)
        self.execv.assert_not_called()

    def test_missing_prefix_and_executable_rejected(self):
        self.prefix.rmdir()
        with self.assertRaisesRegex(RuntimeError, "prefix directory is missing"):
            route.launch(self.args)
        self.prefix.mkdir()
        self.new.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "executable"):
            route.launch(self.args)
        self.execv.assert_not_called()

    def test_bad_runtime_paths_rejected(self):
        for value in ("relative-runtime", "/" + "x" * 120):
            with self.subTest(length=len(value)), patch.dict(os.environ, {"XDG_RUNTIME_DIR": value}):
                with self.assertRaises(RuntimeError):
                    route.launch(self.args)
        self.execv.assert_not_called()

    def test_root_rejected(self):
        with patch.object(route.os, "getuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "non-root"):
                route.launch(self.args)
        self.execv.assert_not_called()

    def test_routing_record_symlink_rejected(self):
        target = self.home / "unchanged-record-target"
        target.write_text("unchanged")
        (self.state / "launch-routing.json").symlink_to(target)
        if hasattr(os, "O_NOFOLLOW"):
            with self.assertRaises(OSError):
                route.launch(self.args)
            self.execv.assert_not_called()
            self.assertEqual(target.read_text(), "unchanged")


class OwnerDirectoryTests(unittest.TestCase):
    def test_private_mode_owner_and_symlink_checks(self):
        with tempfile.TemporaryDirectory(prefix=".directory-test-", dir=HERE) as name:
            directory = Path(name) / "private"
            route.owner_directory(directory, os.getuid(), create=True)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            with self.assertRaises(RuntimeError):
                route.owner_directory(directory, os.getuid() + 1)
            directory.chmod(0o755)
            with self.assertRaises(RuntimeError):
                route.owner_directory(directory, os.getuid())
            directory.chmod(0o700)
            link = Path(name) / "link"
            link.symlink_to(directory)
            with self.assertRaises(RuntimeError):
                route.owner_directory(link, os.getuid())


if __name__ == "__main__":
    unittest.main()
