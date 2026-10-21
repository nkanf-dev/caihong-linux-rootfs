import importlib.util
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("wifi_repair", HERE / "repair_missing_wifi_backend.py")
wifi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wifi)

ORIGINAL = b"# keep this comment\r\n[connection]\r\nwifi.powersave=3\r\nipv4.dhcp-timeout=10\r\n[device]\r\nwifi.backend = iwd\r\nwifi.scan-rand-mac-address=no\r\n"


class FakeSystem:
    def __init__(self, config):
        self.config = config
        self.commands = []
        self.nm = "active"
        self.iwd = "not-found"
        self.wpa = "loaded"
        self.wpa_masked = False
        self.forced_backend = None
        self.fail_service = False
        self.binary_paths = {"/usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service",
                             "/usr/sbin/wpa_supplicant"}

    def exists(self, path):
        return path in self.binary_paths

    def run(self, args, allow_failure=False):
        self.commands.append(args)
        if args == ["NetworkManager", "--print-config"]:
            if self.forced_backend:
                return "[device]\nwifi.backend=" + self.forced_backend + "\n"
            return self.config.read_text()
        if args[:2] == ["systemctl", "show"]:
            name = args[2]
            load = {"iwd.service": self.iwd, "wpa_supplicant.service": self.wpa,
                    "NetworkManager.service": "loaded"}[name]
            active = self.nm if name == "NetworkManager.service" else "inactive"
            unitfile = "masked" if name == "wpa_supplicant.service" and self.wpa_masked else "disabled"
            return "LoadState={}\nActiveState={}\nUnitFileState={}\n".format(load, active, unitfile)
        if args[:2] in (["systemctl", "start"], ["systemctl", "restart"]):
            if self.fail_service:
                raise wifi.RepairError("mock service start failure")
            self.nm = "active"
            return ""
        raise AssertionError(args)

    def service_actions(self):
        return [cmd for cmd in self.commands if cmd[:2] in
                (["systemctl", "start"], ["systemctl", "restart"])]


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp()).resolve()
        self.config = self.directory / "99-valve-wifi-backend.conf"
        self.config.write_bytes(ORIGINAL)
        self.config.chmod(0o640)
        self.backups = self.directory / "backups"
        self.system = FakeSystem(self.config)

    def tearDown(self):
        shutil.rmtree(self.directory)

    def call(self, apply=False):
        with patch.object(wifi, "require_apply_environment"):
            return wifi.repair(apply=apply, config=self.config, backups=self.backups,
                               run=self.system.run, exists=self.system.exists, require_root=False)

    def test_default_plan_never_changes_file_or_services(self):
        result = self.call()
        self.assertEqual(result["action"], "restart")
        self.assertFalse(result["applied"])
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertFalse(self.backups.exists())
        self.assertEqual(self.system.service_actions(), [])

    def test_active_nm_one_restart_and_private_backup(self):
        result = self.call(True)
        expected = ORIGINAL.replace(b"wifi.backend = iwd", b"wifi.backend = wpa_supplicant")
        self.assertEqual(self.config.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(self.system.service_actions(), [["systemctl", "restart", "NetworkManager.service"]])
        self.assertEqual(Path(result["backup"]).read_bytes(), ORIGINAL)
        self.assertEqual(stat.S_IMODE(Path(result["backup"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o700)
        self.assertTrue(result["applied"])

    def test_stopped_nm_gets_one_start_not_restart(self):
        self.system.nm = "inactive"
        self.call(True)
        self.assertEqual(self.system.service_actions(), [["systemctl", "start", "NetworkManager.service"]])

    def test_second_run_is_noop(self):
        self.call(True)
        actions = list(self.system.service_actions())
        second = self.call(True)
        self.assertEqual(second["action"], "none")
        self.assertFalse(second["applied"])
        self.assertEqual(self.system.service_actions(), actions)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_installed_iwd_is_not_changed(self):
        self.system.iwd = "loaded"
        with self.assertRaisesRegex(wifi.RepairError, "iwd is present"):
            self.call(True)
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertFalse(self.backups.exists())

    def test_iwd_binary_without_unit_is_not_changed(self):
        self.system.binary_paths.add("/usr/lib/iwd/iwd")
        with self.assertRaisesRegex(wifi.RepairError, "iwd is present"):
            self.call(True)

    def test_missing_or_masked_wpa_is_not_changed(self):
        for load, masked in (("not-found", False), ("loaded", True)):
            with self.subTest(load=load, masked=masked):
                self.system.wpa, self.system.wpa_masked = load, masked
                with self.assertRaisesRegex(wifi.RepairError, "unavailable or masked"):
                    self.call(True)
        self.assertEqual(self.system.service_actions(), [])

    def test_missing_wpa_binary_is_not_changed(self):
        self.system.binary_paths.remove("/usr/sbin/wpa_supplicant")
        with self.assertRaisesRegex(wifi.RepairError, "binary is unavailable"):
            self.call(True)

    def test_missing_wpa_activation_is_not_changed(self):
        self.system.binary_paths.remove("/usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service")
        with self.assertRaisesRegex(wifi.RepairError, "activation file"):
            self.call(True)

    def test_config_symlink_is_refused(self):
        actual = self.directory / "real.conf"
        self.config.rename(actual)
        self.config.symlink_to(actual)
        with self.assertRaisesRegex(wifi.RepairError, "symlink"):
            self.call(True)
        self.assertEqual(actual.read_bytes(), ORIGINAL)

    def test_backup_symlink_is_refused(self):
        real = self.directory / "private"
        real.mkdir(mode=0o700)
        self.backups.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(wifi.RepairError, "symlink"):
            self.call(True)
        self.assertEqual(self.config.read_bytes(), ORIGINAL)

    def test_world_writable_config_is_refused(self):
        self.config.chmod(0o666)
        with self.assertRaisesRegex(wifi.RepairError, "writable"):
            self.call(True)

    def test_duplicate_or_different_section_backend_is_refused(self):
        for data in (ORIGINAL + b"wifi.backend=iwd\n", b"[connection]\nwifi.backend=iwd\n"):
            with self.subTest(data=data):
                with self.assertRaises(wifi.RepairError):
                    wifi.replace_backend(data)

    def test_device_specific_effective_backend_is_refused(self):
        with self.assertRaisesRegex(wifi.RepairError, "device-specific"):
            wifi.effective_backend("[device]\nwifi.backend=iwd\n[device-specific]\nwifi.backend=iwd\n")

    def test_transitioning_nm_is_refused(self):
        self.system.nm = "activating"
        with self.assertRaisesRegex(wifi.RepairError, "transition"):
            self.call(True)

    def test_config_change_during_review_is_not_overwritten(self):
        real_run = self.system.run
        prints = 0
        def run(args, allow_failure=False):
            nonlocal prints
            if args == ["NetworkManager", "--print-config"]:
                prints += 1
                if prints == 2:
                    self.config.write_bytes(ORIGINAL + b"# concurrent edit\n")
            return real_run(args, allow_failure)
        self.system.run = run
        with self.assertRaisesRegex(wifi.RepairError, "changed during review"):
            self.call(True)
        self.assertEqual(self.config.read_bytes(), ORIGINAL + b"# concurrent edit\n")
        self.assertEqual(self.system.service_actions(), [])
        self.assertFalse(self.backups.exists())

    def test_config_change_while_backing_up_is_not_overwritten(self):
        real_backup = wifi.private_backup
        def backup(directory, data):
            path = real_backup(directory, data)
            self.config.write_bytes(ORIGINAL + b"# another root writer\n")
            return path
        with patch.object(wifi, "private_backup", side_effect=backup):
            with self.assertRaisesRegex(wifi.RepairError, "changed after backup"):
                self.call(True)
        self.assertEqual(self.config.read_bytes(), ORIGINAL + b"# another root writer\n")
        self.assertEqual(self.system.service_actions(), [])
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_postwrite_verification_rolls_back_before_service_action(self):
        real_run = self.system.run
        prints = 0
        def run(args, allow_failure=False):
            nonlocal prints
            if args == ["NetworkManager", "--print-config"]:
                prints += 1
                if prints == 3:
                    return "[device]\nwifi.backend=iwd\n"
            return real_run(args, allow_failure)
        self.system.run = run
        with self.assertRaisesRegex(wifi.RepairError, "overrides"):
            self.call(True)
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(self.system.service_actions(), [])
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_service_failure_keeps_corrected_config_and_does_not_retry(self):
        self.system.fail_service = True
        with self.assertRaisesRegex(wifi.RepairError, "mock service"):
            self.call(True)
        self.assertIn(b"wifi.backend = wpa_supplicant", self.config.read_bytes())
        self.assertEqual(len(self.system.service_actions()), 1)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_apply_platform_gate(self):
        with patch.object(wifi.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(wifi.RepairError, "native Linux root"):
                wifi.require_apply_environment()


class ImageDefaultTests(unittest.TestCase):
    def test_canonical_armada_config_is_wpa_and_retains_powersave(self):
        root = HERE.parents[1]
        canonical = root / "rootfs/armada/etc/NetworkManager/conf.d/99-valve-wifi-backend.conf"
        data = canonical.read_text()
        self.assertEqual(wifi.effective_backend(data), "wpa_supplicant")
        self.assertIn("wifi.powersave=3", data)
        self.assertNotIn("mac-address", data)

    def test_image_verifier_backend_gate_executes_on_fixtures(self):
        root = HERE.parents[1]
        text = (root / "scripts/verify-armada-rootfs.sh").read_text()
        block = text[text.index("wifi_backend_config="):text.index("if [[ -e $target/etc/alsa/state-daemon.conf")]
        cases = (("[device]\nwifi.backend=wpa_supplicant\n", 0),
                 ("[device]\nwifi.backend=iwd\n", 1),
                 ("[connection]\nwifi.backend=wpa_supplicant\n", 1),
                 ("[device]\nwifi.backend=wpa_supplicant\nwifi.backend=iwd\n", 1))
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "etc/NetworkManager/conf.d/99-valve-wifi-backend.conf"
            config.parent.mkdir(parents=True)
            for contents, expected in cases:
                with self.subTest(contents=contents):
                    config.write_text(contents)
                    script = 'target="$1"; failed=0\n' + block + '\nexit "$failed"\n'
                    result = subprocess.run(["bash", "-c", script, "fixture-test", temporary],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_image_verifier_requires_backend_and_activation(self):
        root = HERE.parents[1]
        verifier = (root / "scripts/verify-armada-rootfs.sh").read_text()
        self.assertIn("wifi.backend=wpa_supplicant", verifier)
        self.assertIn("usr/lib/systemd/system/wpa_supplicant.service", verifier)
        self.assertIn("usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service", verifier)


if __name__ == "__main__":
    unittest.main()
