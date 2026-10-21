"""Only authored sources are checked; dependency fixtures never execute."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("source_check", Path(__file__).resolve().parents[1] / "tools/check_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SourceChecks(unittest.TestCase):
    def test_ignores_dependency_and_generated_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "valid.py").write_text("value = 1\n")
            for name in module.EXCLUDED:
                directory = root / name
                directory.mkdir()
                (directory / "invalid.json").write_text("not JSON")
            self.assertEqual(module.check_sources(root)["python"], 1)
            self.assertEqual(module.check_sources(root)["json"], 0)

    def test_invalid_authored_source_still_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "invalid.json").write_text("not JSON")
            with self.assertRaises(ValueError):
                module.check_sources(root)

    def test_symlinked_dependency_tree_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (Path(outside) / "invalid.json").write_text("not JSON")
            (root / "external").symlink_to(outside, target_is_directory=True)
            self.assertEqual(sum(module.check_sources(root).values()), 0)

if __name__ == "__main__":
    unittest.main()
