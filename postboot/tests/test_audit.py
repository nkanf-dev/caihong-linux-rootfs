"""Regression checks use synthetic tokens only; never put real credentials here."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("audit_archive", Path(__file__).resolve().parents[1] / "tools/audit_archive.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class AuditTests(unittest.TestCase):
    def test_safe_placeholder(self):
        self.assertEqual(audit.findings("postboot/proxy/config.yaml.in", b"secret: REPLACE_LOCAL_API_SECRET\n"), [])

    def test_synthetic_credentials(self):
        examples = {
            "bearer-value": "Bearer " + "A" * 24,
            "github-token": "ghp_" + "a" * 30,
            "steam-account-id": "7656119" + "0" * 10,
            ("uu" + "id"): "12345678" + "-1234" * 3 + "-123456789012",
            "private-ipv4": "192" + ".168.7.8",
            "device-mac": ":".join(["12", "34", "56", "78", "9a", "bc"]),
            "personal-home": "/Users/" + "synthetic-user",
            "credential-assignment": "password: synthetic-value",
        }
        for rule, value in examples.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, audit.findings("postboot/example.txt", value.encode()))

    def test_artifacts_and_size(self):
        self.assertIn("forbidden-artifact-path", audit.findings("postboot/capture.so", b"abc"))
        self.assertIn("binary-content", audit.findings("postboot/core.txt", bytes([0, 1])))
        self.assertIn("size-limit", audit.findings("postboot/large.txt", b"x" * (audit.MAX_BYTES + 1)))

if __name__ == "__main__":
    unittest.main()
