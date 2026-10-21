#!/usr/bin/env python3
"""Source-only integrity and evidence checks. No network or target execution."""
import ast
import hashlib
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent


class PreservationTests(unittest.TestCase):
    def test_recorded_source_checksums(self):
        provenance = json.loads((HERE / "evidence/source-provenance.json").read_text())
        for entry in provenance["entries"]:
            path = HERE / entry["path"]
            with self.subTest(path=entry["path"]):
                self.assertTrue(path.is_file())
                if "preserved_sha256" in entry:
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["preserved_sha256"])
                if "git_blob" in entry:
                    data = path.read_bytes()
                    blob = b"blob " + str(len(data)).encode() + b"\0" + data
                    self.assertEqual(hashlib.sha1(blob).hexdigest(), entry["git_blob"])

    def test_pins_agree_with_recipe(self):
        lock = json.loads((HERE / "build/source-lock.json").read_text())
        tree = ast.parse((HERE / "build/container_build.py").read_text())
        constants = {node.targets[0].id: ast.literal_eval(node.value)
                     for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id in {"PIN", "TAG", "SUBMODULES"}}
        self.assertEqual(constants["PIN"], lock["commit"])
        self.assertEqual(constants["TAG"], lock["tag"])
        self.assertEqual(constants["SUBMODULES"], lock["submodules"])

    def test_historical_35_result_summary(self):
        summary = json.loads((HERE / "evidence/synthetic-results.json").read_text())
        self.assertTrue(summary["historical"])
        rows = summary["results"]
        self.assertEqual(len(rows), 35)
        self.assertEqual(sum(row["okay"] for row in rows.values()), 32)
        self.assertFalse(summary["full_suite_pass"])
        self.assertEqual({name for name, row in rows.items() if not row["okay"]},
                         {"execve-seccomp.FEX_NEEDSSECCOMP_1", "smc-same-page", "ptrace-sigbus"})
        negative = [row for row in rows.values() if row["expected"] == "FAIL"]
        self.assertEqual(len(negative), 2)
        self.assertTrue(all(row["okay"] and row["rc"] != 0 for row in negative))

    def test_historical_status_and_vr_attempt(self):
        success = json.loads((HERE / "evidence/SUCCESS.json").read_text())
        checkpoint = json.loads((HERE / "evidence/CHECKPOINT.json").read_text())
        vr = json.loads((HERE / "evidence/VR-ATTEMPT.json").read_text())
        self.assertEqual(success["EAC"]["bootstrap_result"], 301)
        self.assertTrue(success["historical"])
        self.assertTrue(checkpoint["historical"])
        self.assertIn("closed normally", checkpoint["later_transition"])
        self.assertFalse(success["account_login_performed"])
        self.assertFalse(success["world_join_performed"])
        self.assertEqual(vr["change"], "Remove only --no-vr from the known desktop launch options.")
        self.assertIn("pending", vr["validation"])

    def test_python_and_json_parse_without_bytecode(self):
        for path in HERE.rglob("*"):
            if path.is_file() and path.suffix == ".py":
                with self.subTest(path=str(path.relative_to(HERE))):
                    compile(path.read_text(), str(path), "exec")
            elif path.is_file() and path.suffix == ".json":
                with self.subTest(path=str(path.relative_to(HERE))):
                    json.loads(path.read_text())

    def test_no_runtime_binaries_or_personal_home_paths(self):
        personal = re.compile("/" + "Users/|/var/" + "home/")
        for path in HERE.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                with self.subTest(path=str(path.relative_to(HERE))):
                    self.assertNotEqual(data[:4], b"\x7fELF")
                    self.assertNotIn(path.suffix, {".core", ".zst", ".pyc", ".o", ".so", ".exe"})
                    self.assertIsNone(personal.search(data.decode()))


if __name__ == "__main__":
    unittest.main()
