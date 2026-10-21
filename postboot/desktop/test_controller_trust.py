import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("controller_trust", Path(__file__).with_name("controller-trust.py"))
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def synthetic_address():
    return ":".join(["00"] * 6)


class ControllerTrustTests(unittest.TestCase):
    def test_info_outputs_only_state_booleans(self):
        output = "Device REPLACE_LOCAL_ID\n  Paired: yes\n  Trusted: no\n  Connected: yes\n"
        with patch.object(controller.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
            self.assertEqual(controller.state(synthetic_address()),
                             {"paired": True, "trusted": False, "connected": True})

    def test_repair_trusts_and_connects_only_a_paired_device(self):
        before = {"paired": True, "trusted": False, "connected": False}
        after = {"paired": True, "trusted": True, "connected": True}
        address = synthetic_address()
        output = io.StringIO()
        with patch.object(controller, "state", side_effect=[before, after]), \
             patch.object(controller.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, \
             patch("sys.argv", ["controller-trust.py", "repair", address]), contextlib.redirect_stdout(output):
            controller.main()
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["bluetoothctl", "trust", address], ["bluetoothctl", "connect", address]])
        self.assertEqual(json.loads(output.getvalue()), {"before": before, "after": after})
        self.assertNotIn(address, output.getvalue())

    def test_unpaired_device_is_not_modified(self):
        with patch.object(controller, "state", return_value={"paired": False}), \
             patch.object(controller.subprocess, "run") as run, \
             patch("sys.argv", ["controller-trust.py", "repair", synthetic_address()]):
            with self.assertRaisesRegex(RuntimeError, "not paired"):
                controller.main()
        run.assert_not_called()

    def test_tool_failure_does_not_expose_output(self):
        with patch.object(controller.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "REPLACE_LOCAL_ID", "")):
            with self.assertRaisesRegex(RuntimeError, "Controller info failed") as error:
                controller.state(synthetic_address())
        self.assertNotIn("REPLACE_LOCAL_ID", str(error.exception))


if __name__ == "__main__":
    unittest.main()
