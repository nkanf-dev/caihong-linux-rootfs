"""Steam app250820 entry interleavings. No live runtime execution."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import steamvr_auto as auto
from dual_mode import LaunchError

class AutoTests(unittest.TestCase):
    def test_validates_original_chain_before_receipt_then_delegates_once(self):
        calls=[]
        outer=Mock()
        outer.__file__="/fixture/outer.py"
        outer.prepare.side_effect=lambda args,env:calls.append("validate")
        outer.main.side_effect=lambda:calls.append("outer")
        runtime=Mock()
        runtime.prepare.side_effect=lambda:calls.append("receipt")
        runtime.admission_live.return_value=False
        runtime.settings=Path("/fixture/settings")
        runtime.runtime_state=Path("/fixture/runtime")
        runtime.state=Path("/fixture/launcher")
        with patch.object(auto,"load_outer",return_value=outer),patch.object(auto,"Runtime",return_value=runtime),              patch.object(auto,"private_lock") as lock,patch.object(auto,"prepare_clean",side_effect=lambda *a,**k:calls.append("receipt")), \
             patch.object(auto.Path,"read_text",return_value="1 (python) "+" ".join(["0"]*20)),patch.object(auto,"write_private"):
            auto.run(["original"],{"SteamAppId":"250820"})
        self.assertEqual(calls,["validate","receipt","outer"])
        outer.main.assert_called_once()

    def test_live_admission_rejects_second_entry_before_receipt_write(self):
        runtime=Mock()
        runtime.admission_live.return_value=True
        outer=Mock()
        with patch.object(auto,"load_outer",return_value=outer),patch.object(auto,"Runtime",return_value=runtime), \
             patch.object(auto,"private_lock"),patch.object(auto,"prepare_clean") as receipt, \
             self.assertRaisesRegex(LaunchError,"already"):
            auto.run(["original"],{"SteamAppId":"250820"})
        receipt.assert_not_called()
        outer.main.assert_not_called()

    def test_validation_failure_does_not_create_receipt(self):
        outer=Mock()
        outer.__file__="/fixture/outer.py"
        outer.prepare.side_effect=ValueError("bad app")
        with patch.object(auto,"load_outer",return_value=outer),patch.object(auto,"Runtime") as runtime,              self.assertRaises(ValueError):
            auto.run(["original"],{"SteamAppId":"438100"})
        runtime.assert_not_called()
        outer.main.assert_not_called()

if __name__=="__main__":unittest.main()
