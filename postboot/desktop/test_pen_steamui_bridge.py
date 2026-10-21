import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pen_steamui_bridge as b


class FakeOutput:
    def __init__(self):
        self.events = []

    def motion(self, x, y):
        self.events.append(("motion", x, y))

    def button(self, down):
        self.events.append(("button", down))


class TransformTests(unittest.TestCase):
    def test_corners_and_clamp(self):
        self.assertEqual(b.transform(0, 0, 3000, 2120, 0), (0, 0))
        self.assertEqual(b.transform(29999, 21199, 3000, 2120, 0), (2999, 2119))
        self.assertEqual(b.transform(-30, 30000, 3000, 2120, 0), (0, 2119))
        self.assertEqual(b.transform(15000, 10600, 3000, 2120, 0), (1500, 1060))

    def test_rotations(self):
        expected = {0: (0, 0), 90: (2999, 0), 180: (2999, 2119), 270: (0, 2119)}
        for rotation, corner in expected.items():
            with self.subTest(rotation=rotation):
                self.assertEqual(b.transform(0, 0, 3000, 2120, rotation), corner)
        self.assertEqual(b.transform(29999, 0, 3000, 2120, 90), (2999, 2119))
        with self.assertRaises(ValueError):
            b.transform(0, 0, 0, 10, 0)

    def test_aspect_matches_evidence(self):
        self.assertLess(abs((b.X_MAX + 1) / (b.Y_MAX + 1) - 3000 / 2120), 0.00001)


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.out = FakeOutput()
        self.state = b.Bridge(self.out, 3000, 2120, 0, tip=False, proximity=False)
        self.state.set_gate(True)
        self.now = 0.0

    def frame(self, *events):
        for kind, code, value in events:
            self.state.event(kind, code, value, self.now)
        self.state.event(b.EV_SYN, b.SYN_REPORT, 0, self.now)
        self.now += 0.01

    def down(self):
        self.frame((b.EV_ABS, b.ABS_X, 1000), (b.EV_ABS, b.ABS_Y, 1000),
                   (b.EV_KEY, b.BTN_TOOL_PEN, 1), (b.EV_KEY, b.BTN_TOUCH, 1))

    def test_no_emission_before_syn_and_fresh_complete_press(self):
        self.state.event(b.EV_ABS, b.ABS_X, 1000, 0)
        self.state.event(b.EV_ABS, b.ABS_Y, 1000, 0)
        self.state.event(b.EV_KEY, b.BTN_TOOL_PEN, 1, 0)
        self.state.event(b.EV_KEY, b.BTN_TOUCH, 1, 0)
        self.assertEqual(self.out.events, [])
        self.state.event(b.EV_SYN, b.SYN_REPORT, 0, 0)
        self.assertEqual([e[0] for e in self.out.events], ["motion", "button"])
        self.assertTrue(self.state.pressed)
        self.frame((b.EV_KEY, b.BTN_TOUCH, 0))
        self.assertIn(("button", False), self.out.events)
        self.assertFalse(self.state.pressed)

    def test_incomplete_press_never_uses_stale_coordinates(self):
        self.frame((b.EV_ABS, b.ABS_X, 1000), (b.EV_ABS, b.ABS_Y, 1000),
                   (b.EV_KEY, b.BTN_TOOL_PEN, 1))
        self.frame((b.EV_KEY, b.BTN_TOUCH, 1))
        self.frame((b.EV_ABS, b.ABS_X, 2000), (b.EV_ABS, b.ABS_Y, 2000))
        self.assertFalse(self.state.pressed)
        self.assertNotIn(("button", True), self.out.events)

    def test_starting_with_tip_down_needs_up(self):
        self.state = b.Bridge(self.out, 3000, 2120, 0, tip=True, proximity=True)
        self.state.set_gate(True)
        self.down()
        self.assertFalse(self.state.pressed)
        self.frame((b.EV_KEY, b.BTN_TOUCH, 0))
        self.down()
        self.assertTrue(self.state.pressed)

    def test_gate_loss_releases_and_needs_new_up(self):
        self.down()
        self.state.set_gate(False)
        self.assertEqual(self.out.events[-1], ("button", False))
        self.state.set_gate(True)
        self.down()
        self.assertFalse(self.state.pressed)
        self.frame((b.EV_KEY, b.BTN_TOUCH, 0))
        self.down()
        self.assertTrue(self.state.pressed)

    def test_off_gate_never_moves_or_clicks(self):
        self.state.set_gate(False)
        self.down()
        self.assertEqual(self.out.events, [])

    def test_timeout_releases_and_blocks(self):
        self.down()
        self.state.tick(0.999)
        self.assertTrue(self.state.pressed)
        self.state.tick(1.0)
        self.assertFalse(self.state.pressed)
        self.assertEqual(self.out.events[-1], ("button", False))
        self.down()
        self.assertFalse(self.state.pressed)

    def test_idle_timeout_keeps_known_tip_up_armed(self):
        self.frame((b.EV_KEY, b.BTN_TOOL_PEN, 1), (b.EV_ABS, b.ABS_X, 100),
                   (b.EV_ABS, b.ABS_Y, 100))
        self.state.tick(2.0)
        self.assertFalse(self.state.blocked)
        self.down()
        self.assertTrue(self.state.pressed)

    def test_no_motion_outside_proximity_and_ignored_side_buttons(self):
        self.frame((b.EV_ABS, b.ABS_X, 100), (b.EV_ABS, b.ABS_Y, 200))
        self.assertEqual(self.out.events, [])
        self.frame((b.EV_KEY, b.BTN_TOOL_PEN, 1))
        self.assertEqual(self.out.events[-1][0], "motion")
        self.frame((b.EV_KEY, 331, 1), (b.EV_KEY, 332, 1), (b.EV_ABS, 24, 8000))
        self.assertNotIn(("button", True), self.out.events)

    def test_dropped_sync_releases_discards_until_report_and_up(self):
        self.down()
        self.state.event(b.EV_SYN, b.SYN_DROPPED, 0, self.now)
        self.assertFalse(self.state.pressed)
        self.down()
        self.assertFalse(self.state.pressed)
        self.frame((b.EV_KEY, b.BTN_TOUCH, 0))
        self.down()
        self.assertTrue(self.state.pressed)

    def test_shutdown_is_idempotent(self):
        self.down()
        self.state.release("shutdown")
        self.state.release("shutdown")
        self.assertEqual(self.out.events.count(("button", False)), 1)

    def test_immediate_press_gate_refusal_blocks_until_up(self):
        original_button = self.out.button
        self.out.button = lambda down: False if down else original_button(False)
        self.down()
        self.assertFalse(self.state.pressed)
        self.assertTrue(self.state.blocked)
        self.assertFalse(self.state.gate)
        self.out.button = original_button
        self.state.set_gate(True)
        self.down()
        self.assertFalse(self.state.pressed)
        self.frame((b.EV_KEY, b.BTN_TOUCH, 0))
        self.down()
        self.assertTrue(self.state.pressed)

    def test_gate_loss_clears_partial_frame(self):
        self.state.event(b.EV_ABS, b.ABS_X, 100, 0)
        self.state.event(b.EV_ABS, b.ABS_Y, 200, 0)
        self.state.event(b.EV_KEY, b.BTN_TOUCH, 1, 0)
        self.state.set_gate(False)
        self.state.set_gate(True)
        self.frame((b.EV_KEY, b.BTN_TOOL_PEN, 1))
        self.assertFalse(self.state.pressed)


class PropertyTests(unittest.TestCase):
    def test_cardinal_uses_native_ulong_stride(self):
        storage = (ctypes.c_ulong * 2)(769, 4294967295)
        pointer = ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte))
        self.assertEqual(b.decode_cardinals(6, 32, 2, pointer, 6), (769, 4294967295))

    def test_unavailable_wrong_type_format_and_null(self):
        storage = (ctypes.c_ulong * 1)(769)
        pointer = ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte))
        for actual_type, fmt, count, data in [(0, 0, 0, None), (4, 32, 1, pointer),
                                              (6, 8, 1, pointer), (6, 32, 1, None)]:
            self.assertIsNone(b.decode_cardinals(actual_type, fmt, count, data, 6))

    def test_gate_requires_exact_single_values(self):
        props = {"GAMESCOPE_PID": (42,), "GAMESCOPE_XWAYLAND_SERVER_ID": (0,),
                 "GAMESCOPE_FOCUSED_WINDOW": (33554485,),
                 "GAMESCOPE_FOCUSED_APP": (769,), "GAMESCOPE_FOCUSED_APP_GFX": (769,)}
        self.assertTrue(b.focus_allowed(props.get, 42))
        for name in props:
            for value in [None, (), (0,), (770,), (769, 769)]:
                if name == "GAMESCOPE_XWAYLAND_SERVER_ID" and value == (0,):
                    continue
                if name == "GAMESCOPE_FOCUSED_WINDOW" and value in ((769,), (770,)):
                    continue
                changed = dict(props, **{name: value})
                self.assertFalse(b.focus_allowed(changed.get, 42), (name, value))

    def test_property_read_failure_gates_off(self):
        def broken(name):
            raise OSError("X unavailable")
        self.assertFalse(b.focus_allowed(broken, 42))


class XAdapterTests(unittest.TestCase):
    def fake_adapter(self, actual_type=6, fmt=32, values=(769,), status=0, remaining=0):
        adapter = b.X11.__new__(b.X11)
        adapter.display, adapter.root, adapter.cardinal = 1, 2, 6
        adapter.atoms = {"GAMESCOPE_FOCUSED_APP": 9}
        adapter.dry_run = True
        adapter.pre_press = lambda: True
        storage = (ctypes.c_ulong * max(1, len(values)))(*values)
        pointer = ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte))
        class Lib:
            freed = 0
            def XGetWindowProperty(self, display, root, atom, offset, length, delete,
                                   requested_type, type_out, fmt_out, count_out,
                                   remaining_out, data_out):
                ctypes.cast(type_out, ctypes.POINTER(ctypes.c_ulong))[0] = actual_type
                ctypes.cast(fmt_out, ctypes.POINTER(ctypes.c_int))[0] = fmt
                ctypes.cast(count_out, ctypes.POINTER(ctypes.c_ulong))[0] = len(values)
                ctypes.cast(remaining_out, ctypes.POINTER(ctypes.c_ulong))[0] = remaining
                ctypes.cast(data_out, ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))[0] = pointer
                return status
            def XFree(self, data):
                self.freed += 1
        adapter.lib = Lib()
        return adapter

    def test_real_property_reader_native_layout_and_free(self):
        adapter = self.fake_adapter(values=(769, 4294967295))
        self.assertEqual(adapter.read("GAMESCOPE_FOCUSED_APP"), (769, 4294967295))
        self.assertEqual(adapter.lib.freed, 1)

    def test_real_property_reader_unavailable_invalid_and_truncated(self):
        for kwargs in [dict(actual_type=0, fmt=0, values=()), dict(actual_type=4),
                       dict(fmt=8), dict(status=1), dict(remaining=4)]:
            with self.subTest(kwargs=kwargs):
                adapter = self.fake_adapter(**kwargs)
                self.assertIsNone(adapter.read("GAMESCOPE_FOCUSED_APP"))
                self.assertEqual(adapter.lib.freed, 1)
        adapter = self.fake_adapter()
        self.assertIsNone(adapter.read("MISSING_ATOM"))
        self.assertEqual(adapter.lib.freed, 0)

    def test_dry_run_never_calls_xtest(self):
        adapter = self.fake_adapter()
        adapter.motion(100, 200)
        self.assertTrue(adapter.button(True))
        self.assertTrue(adapter.button(False))

    def test_live_button_checks_fresh_gate_immediately_before_xtest(self):
        from types import SimpleNamespace
        adapter = self.fake_adapter()
        adapter.dry_run = False
        calls = []
        adapter.pre_press = lambda: calls.append("gate") or True
        adapter.xtst = SimpleNamespace(XTestFakeButtonEvent=lambda *args: calls.append("press") or 1)
        adapter.lib.XSync = lambda *args: calls.append("sync")
        self.assertTrue(adapter.button(True))
        self.assertEqual(calls, ["gate", "press", "sync"])
        calls.clear()
        adapter.pre_press = lambda: False
        self.assertFalse(adapter.button(True))
        self.assertEqual(calls, [])
        self.assertTrue(adapter.button(False))
        self.assertEqual(calls, ["press", "sync"])


class InputAndDiscoveryTests(unittest.TestCase):
    def test_native_event_layout_and_partial_bytes(self):
        self.assertEqual(b.INPUT_EVENT.size, 2 * ctypes.sizeof(ctypes.c_long) + 8)
        wire = b.INPUT_EVENT.pack(100, 200, b.EV_KEY, b.BTN_TOUCH, 1)
        parser = b.EventParser()
        self.assertEqual(parser.feed(wire[:7]), [])
        self.assertEqual(parser.feed(wire[7:]), [(b.EV_KEY, b.BTN_TOUCH, 1)])

    def test_gamescope_pid_must_match_uid_observed_comm_and_exact_elf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "proc"
            entry = proc / "42"
            entry.mkdir(parents=True)
            executable = root / "usr" / "bin" / "gamescope"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"\x7fELFexample")
            (entry / "comm").write_text("gamescope-wl\n")
            (entry / "exe").symlink_to(executable)
            self.assertTrue(b.gamescope_process_valid(42, proc, executable))
            with patch.object(b.os, "getuid", return_value=b.os.getuid() + 1):
                self.assertFalse(b.gamescope_process_valid(42, proc, executable))
            for comm in ("gamescope", "gamescope-wl-extra", "kwin_wayland"):
                (entry / "comm").write_text(comm + "\n")
                self.assertFalse(b.gamescope_process_valid(42, proc, executable))
            (entry / "comm").write_text("gamescope-wl\n")
            self.assertFalse(b.gamescope_process_valid(99, proc, executable))
            self.assertFalse(b.gamescope_process_valid(0, proc, executable))
            executable.write_bytes(b"not-an-ELF")
            self.assertFalse(b.gamescope_process_valid(42, proc, executable))

    def test_gamescope_pid_wrong_or_missing_executable_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "proc"
            entry = proc / "42"
            entry.mkdir(parents=True)
            (entry / "comm").write_text("gamescope-wl\n")
            executable = root / "gamescope"
            executable.write_bytes(b"\x7fELFexample")
            other = root / "other"
            other.write_bytes(b"\x7fELFexample")
            (entry / "exe").symlink_to(other)
            self.assertFalse(b.gamescope_process_valid(42, proc, executable))
            (entry / "exe").unlink()
            self.assertFalse(b.gamescope_process_valid(42, proc, executable))
            # Canonical aliases to the same actual ELF are accepted.
            alias = root / "alias"
            alias.symlink_to(executable)
            (entry / "exe").symlink_to(alias)
            self.assertTrue(b.gamescope_process_valid(42, proc, executable))
            executable.unlink()
            self.assertFalse(b.gamescope_process_valid(42, proc, executable))

    def test_only_exact_pen_name_auto_and_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, device_name in [("event5", "Novatek NT36532E Touchscreen"),
                                      ("event6", b.DEVICE_NAME), ("event7", "OnePlus Pencil Pro Mouse")]:
                (root / name / "device").mkdir(parents=True)
                (root / name / "device" / "name").write_text(device_name + "\n")
            self.assertEqual(b.find_pen("auto", root), Path("/dev/input/event6"))
            self.assertEqual(b.find_pen("/dev/input/event6", root), Path("/dev/input/event6"))
            with self.assertRaises(b.BridgeError):
                b.find_pen("/dev/input/event7", root)
            with self.assertRaises(b.BridgeError):
                b.find_pen("/tmp/event6", root)

    def test_display_discovery_and_override_must_match_steam(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            p = proc / "123"
            p.mkdir()
            (p / "comm").write_text("steam\n")
            (p / "environ").write_bytes(b"DISPLAY=:7\0XDG_CURRENT_DESKTOP=gamescope\0XAUTHORITY=/secret/auth\0")
            session = b.steam_session(None, None, proc)
            self.assertEqual(session.display, ":7")
            self.assertEqual(session.pid, 123)
            self.assertEqual(b.steam_session(123, ":7", proc).display, ":7")
            with self.assertRaises(b.BridgeError):
                b.steam_session(123, ":0", proc)
            (p / "environ").write_bytes(b"DISPLAY=host:7\0XDG_CURRENT_DESKTOP=gamescope\0")
            with self.assertRaises(b.BridgeError):
                b.steam_session(123, None, proc)


if __name__ == "__main__":
    unittest.main()
