#!/usr/bin/env python3
"""Host-only mocked FnTable tests. No CDLL, /proc, device, URI, or OpenVR Init."""
import ctypes
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest

HELPER = Path(__file__).with_name("read_native_steam_readiness.py")
spec = importlib.util.spec_from_file_location("readiness002", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FakeLibrary:
    def __init__(self, *, interface_error=0, handle_error=0, batch_error=0,
                 property_error=0, tag=5, payload=b"mock-private-value\0",
                 required=None):
        self.calls = []
        self.interface_error = interface_error
        def to_handle(out, path):
            self.calls.append(("StringToHandle", path))
            out[0] = 1234
            return handle_error
        def read(root, out, count):
            self.calls.append(("ReadPathBatch", root, count))
            row = out[0]
            assert row.ulPath == 1234
            assert row.unBufferSize == module.MAX_BYTES
            assert row.unTag == 0
            row.eError = property_error
            row.unTag = tag
            row.unRequiredBufferSize = len(payload) if required is None else required
            if len(payload) <= row.unBufferSize:
                ctypes.memmove(row.pvBuffer, payload, len(payload))
            return batch_error
        self.keep_read = module.READ_BATCH(read)
        self.keep_handle = module.TO_HANDLE(to_handle)
        self.table = (ctypes.c_void_p * 4)(
            ctypes.cast(self.keep_read, ctypes.c_void_p).value, 0,
            ctypes.cast(self.keep_handle, ctypes.c_void_p).value, 0)
    def VR_GetGenericInterface(self, version, error):
        self.calls.append(("GetGenericInterface", version))
        ctypes.cast(error, ctypes.POINTER(ctypes.c_int32))[0] = self.interface_error
        return 0 if self.interface_error else ctypes.addressof(self.table)

class ReadTests(unittest.TestCase):
    def test_layout_and_source_pin(self):
        self.assertEqual(ctypes.sizeof(module.PathRead), 40)
        self.assertEqual(module.ABI_SOURCE_COMMIT,
                         "0924064316de3effbcd1acf1e309182a2deb1c05")
    def test_success_uses002_and_exact_root(self):
        fake = FakeLibrary()
        status, value = module.read_property(fake)
        self.assertEqual(value, "mock-private-value")
        self.assertEqual(status["tag"], 5)
        self.assertEqual(fake.calls, [
            ("GetGenericInterface", b"FnTable:IVRPaths_002"),
            ("StringToHandle", b"/steam/vr_connection_ready"),
            ("ReadPathBatch", 0x600000000, 1)])
    def test_interface_failure_does_not_call_methods(self):
        fake = FakeLibrary(interface_error=105)
        status, value = module.read_property(fake)
        self.assertIsNone(value)
        self.assertEqual(status["interface_error"], 105)
        self.assertEqual(len(fake.calls), 1)
    def test_handle_failure_does_not_read(self):
        fake = FakeLibrary(handle_error=4)
        status, value = module.read_property(fake)
        self.assertIsNone(value)
        self.assertEqual(status["handle_error"], 4)
        self.assertEqual(len(fake.calls), 2)
    def test_batch_property_and_type_fail_closed(self):
        for config in [{"batch_error": 5}, {"property_error": 4}, {"tag": 2}]:
            with self.subTest(config=config):
                status, value = module.read_property(FakeLibrary(**config))
                self.assertIsNone(value)
    def test_invalid_lengths_fail_closed(self):
        for length in [0, 1, module.MAX_BYTES + 1]:
            status, value = module.read_property(FakeLibrary(required=length))
            self.assertIsNone(value)
    def test_invalid_termination_and_utf8_fail_closed(self):
        for payload in [b"unclosed", b"a\0b\0", b"\xff\0"]:
            status, value = module.read_property(FakeLibrary(payload=payload))
            self.assertIsNone(value)
    def test_private_output_is0600_and_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d)
            parent.chmod(0o700)
            output = parent / "token"
            module.write_private_value(output, "mock-only")
            self.assertEqual(output.read_text(), "mock-only")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                module.write_private_value(output, "replacement")
    def test_symlink_output_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            actual = root / "actual"
            actual.mkdir(mode=0o700)
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.write_private_value(alias / "token", "mock-only")
            self.assertFalse((actual / "token").exists())
    def test_nonprivate_output_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d)
            parent.chmod(0o755)
            with self.assertRaises(ValueError):
                module.write_private_value(parent / "token", "mock-only")

if __name__ == "__main__":
    unittest.main(verbosity=2)
