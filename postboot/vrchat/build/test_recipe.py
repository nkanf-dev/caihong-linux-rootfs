#!/usr/bin/env python3
"""Host-side unit checks. Does not contact or execute on the device."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("validate_fex",HERE/"validate_fex.py")
v=importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

class Checks(unittest.TestCase):
    def test_pinned_table(self):
        rows=v.cases(HERE/"evidence")
        self.assertEqual(len(rows),33)
        self.assertTrue(set(v.MINIMUM).issubset({r[0] for r in rows}))
        self.assertEqual(sum(r[2]=="FAIL" for r in rows),2)

    def test_elf_machine(self):
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            path=Path(d)/"elf"
            data=bytearray(64)
            data[:6]=b"\x7fELF\x02\x01"
            struct.pack_into("<H",data,18,183)
            path.write_bytes(data)
            v.elf(path,183)
            with self.assertRaises(RuntimeError):
                v.elf(path,62)

    def test_expected_exit_codes(self):
        class P:
            pid=10000000
            def __init__(self,*args,**kwargs):
                kwargs["stdout"].write(self.text)
            def wait(self,timeout):
                return self.rc
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            path=Path(d)/"log"
            with patch.object(v.subprocess,"Popen",P):
                P.text="RESULT: PASS\n";P.rc=0
                self.assertTrue(v.one_test(["unused"],d,{},path)["okay"])
                P.rc=1
                self.assertFalse(v.one_test(["unused"],d,{},path)["okay"])
                P.text="RESULT: FAIL\n";P.rc=1
                self.assertTrue(v.one_test(["unused"],d,{},path,expected="FAIL")["okay"])
                P.rc=0
                self.assertFalse(v.one_test(["unused"],d,{},path,expected="FAIL")["okay"])
                P.text="RESULT: SKIP\n";P.rc=0
                self.assertFalse(v.one_test(["unused"],d,{},path)["okay"])

    def test_short_socket(self):
        s="/run/user/1000/cvf-abcdefgh/data/Server/1000.FEXServer.Socket"
        self.assertLess(len(s.encode()),108)

    def test_no_cpu_quota(self):
        source=(HERE/"validate_fex.py").read_text()
        self.assertNotIn('"--cpus=2"',source)
        self.assertIn('"FEX_PORTABLE":"1"',source)
        self.assertIn('"--foreground","--kill"',source)

if __name__=="__main__":
    unittest.main()
