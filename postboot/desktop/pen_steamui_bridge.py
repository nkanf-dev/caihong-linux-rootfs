#!/usr/bin/env python3
"""Read the Novatek pen and map it to a pointer only inside Gamescope SteamUI."""

import argparse
import ctypes as C
import ctypes.util
import dataclasses
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import struct
import sys
import time

DEVICE_NAME = "Novatek NT36532E Pen"
X_MAX, Y_MAX = 29999, 21199
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y = 0, 1
BTN_TOOL_PEN, BTN_TOUCH = 320, 330
INPUT_EVENT = struct.Struct("@llHHi")
FOCUS_NAMES = ("GAMESCOPE_PID", "GAMESCOPE_XWAYLAND_SERVER_ID", "GAMESCOPE_FOCUSED_WINDOW",
               "GAMESCOPE_FOCUSED_APP", "GAMESCOPE_FOCUSED_APP_GFX")


class BridgeError(Exception):
    pass


def log(event, **fields):
    print(json.dumps(dict(event=event, **fields), sort_keys=True), flush=True)


def transform(x, y, width, height, rotation):
    if width < 1 or height < 1 or rotation not in (0, 90, 180, 270):
        raise ValueError("invalid screen size or rotation")
    u, v = min(1, max(0, x / X_MAX)), min(1, max(0, y / Y_MAX))
    if rotation == 90:
        u, v = 1 - v, u
    elif rotation == 180:
        u, v = 1 - u, 1 - v
    elif rotation == 270:
        u, v = v, 1 - u
    return int(u * (width - 1) + 0.5), int(v * (height - 1) + 0.5)


class Bridge:
    def __init__(self, output, width, height, rotation, tip=None, proximity=False):
        self.output = output
        self.width, self.height, self.rotation = width, height, rotation
        self.tip, self.proximity = tip, proximity
        self.x = self.y = None
        self.gate = self.pressed = False
        self.blocked = tip is not False
        self.pending = {}
        self.dropping = False
        self.last_report = None
        self.counts = dict(reports=0, motions=0, presses=0, releases=0,
                           gate_losses=0, timeouts=0, dropped=0, incomplete_tips=0)

    def release(self, reason):
        if self.pressed:
            self.output.button(False)
            self.pressed = False
            self.counts["releases"] += 1

    def set_gate(self, enabled):
        if self.gate and not enabled:
            self.release("gate-loss")
            self.blocked = True
            self.pending.clear()
            self.counts["gate_losses"] += 1
        self.gate = enabled

    def tick(self, now):
        if self.last_report is not None and now - self.last_report >= 1.0:
            if self.pressed:
                self.counts["timeouts"] += 1
            if self.tip is not False:
                self.blocked = True
            self.release("timeout")
            self.pending.clear()
            self.x = self.y = None
            self.last_report = None

    def event(self, kind, code, value, now):
        if kind == EV_SYN and code == SYN_DROPPED:
            self.release("dropped")
            self.blocked = self.dropping = True
            self.pending.clear()
            self.x = self.y = None
            self.proximity = False
            self.tip = None
            self.counts["dropped"] += 1
            return
        if self.dropping:
            if kind == EV_SYN and code == SYN_REPORT:
                self.dropping = False
            return
        if kind == EV_ABS and code in (ABS_X, ABS_Y):
            self.pending[(kind, code)] = value
        elif kind == EV_KEY and code in (BTN_TOUCH, BTN_TOOL_PEN) and value in (0, 1):
            self.pending[(kind, code)] = bool(value)
        elif kind == EV_SYN and code == SYN_REPORT:
            self.report(now)

    def report(self, now):
        self.last_report = now
        self.counts["reports"] += 1
        frame, self.pending = self.pending, {}
        previous_tip = self.tip
        self.x = frame.get((EV_ABS, ABS_X), self.x)
        self.y = frame.get((EV_ABS, ABS_Y), self.y)
        self.tip = frame.get((EV_KEY, BTN_TOUCH), self.tip)
        self.proximity = frame.get((EV_KEY, BTN_TOOL_PEN), self.proximity)
        if frame.get((EV_KEY, BTN_TOUCH)) is False:
            self.blocked = False
        if frame.get((EV_KEY, BTN_TOOL_PEN)) is False:
            self.release("proximity-out")
            self.blocked = False
            self.tip = False
            self.x = self.y = None
        if self.tip is False:
            self.release("tip-up")
        if not self.gate or not self.proximity or self.x is None or self.y is None:
            return
        self.output.motion(*transform(self.x, self.y, self.width, self.height, self.rotation))
        self.counts["motions"] += 1
        fresh_down = previous_tip is False and frame.get((EV_KEY, BTN_TOUCH)) is True
        if fresh_down and not self.blocked:
            complete = (EV_ABS, ABS_X) in frame and (EV_ABS, ABS_Y) in frame
            if complete:
                if self.output.button(True) is False:
                    self.set_gate(False)
                    self.blocked = True
                    return
                self.pressed = True
                self.counts["presses"] += 1
            else:
                self.blocked = True
                self.counts["incomplete_tips"] += 1


class EventParser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        events = []
        while len(self.buffer) >= INPUT_EVENT.size:
            _, _, kind, code, value = INPUT_EVENT.unpack_from(self.buffer)
            del self.buffer[:INPUT_EVENT.size]
            events.append((kind, code, value))
        return events


def decode_cardinals(actual_type, actual_format, count, data, cardinal_atom):
    if actual_type != cardinal_atom or actual_format != 32 or count < 1 or not data:
        return None
    # Xlib returns each format-32 item in a native unsigned long, also on LP64.
    values = C.cast(data, C.POINTER(C.c_ulong))
    return tuple(int(values[i]) & 0xffffffff for i in range(count))


def focus_allowed(read, gamescope_pid):
    try:
        window = read("GAMESCOPE_FOCUSED_WINDOW")
        return (read("GAMESCOPE_PID") == (gamescope_pid,) and
                read("GAMESCOPE_XWAYLAND_SERVER_ID") == (0,) and
                window is not None and len(window) == 1 and window[0] > 0 and
                read("GAMESCOPE_FOCUSED_APP") == (769,) and
                read("GAMESCOPE_FOCUSED_APP_GFX") == (769,))
    except (OSError, BridgeError):
        return False


class XPropertyEvent(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("window", C.c_ulong), ("atom", C.c_ulong),
                ("time", C.c_ulong), ("state", C.c_int)]


class XEvent(C.Union):
    _fields_ = [("type", C.c_int), ("property", XPropertyEvent), ("pad", C.c_long * 24)]


class X11:
    def __init__(self, display, dry_run=False):
        self.display = None
        self.xtst = None
        self.dry_run = dry_run
        self.pre_press = None
        name = C.util.find_library("X11")
        if not name:
            raise BridgeError("libX11 is unavailable")
        self.lib = C.CDLL(name)
        signatures = {
            "XOpenDisplay": (C.c_void_p, [C.c_char_p]),
            "XDefaultScreen": (C.c_int, [C.c_void_p]),
            "XRootWindow": (C.c_ulong, [C.c_void_p, C.c_int]),
            "XDisplayWidth": (C.c_int, [C.c_void_p, C.c_int]),
            "XDisplayHeight": (C.c_int, [C.c_void_p, C.c_int]),
            "XInternAtom": (C.c_ulong, [C.c_void_p, C.c_char_p, C.c_int]),
            "XGetWindowProperty": (C.c_int, [C.c_void_p, C.c_ulong, C.c_ulong, C.c_long,
                C.c_long, C.c_int, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_int),
                C.POINTER(C.c_ulong), C.POINTER(C.c_ulong), C.POINTER(C.POINTER(C.c_ubyte))]),
            "XFree": (C.c_int, [C.c_void_p]),
            "XFlush": (C.c_int, [C.c_void_p]),
            "XSync": (C.c_int, [C.c_void_p, C.c_int]),
            "XSelectInput": (C.c_int, [C.c_void_p, C.c_ulong, C.c_long]),
            "XConnectionNumber": (C.c_int, [C.c_void_p]),
            "XPending": (C.c_int, [C.c_void_p]),
            "XNextEvent": (C.c_int, [C.c_void_p, C.POINTER(XEvent)]),
            "XCloseDisplay": (C.c_int, [C.c_void_p]),
        }
        for function, (restype, argtypes) in signatures.items():
            getattr(self.lib, function).restype = restype
            getattr(self.lib, function).argtypes = argtypes
        self.display = self.lib.XOpenDisplay(display.encode())
        if not self.display:
            raise BridgeError("cannot open Steam X display")
        self.screen = self.lib.XDefaultScreen(self.display)
        self.root = self.lib.XRootWindow(self.display, self.screen)
        self.cardinal = self.lib.XInternAtom(self.display, b"CARDINAL", 1)
        self.atoms = {name: self.lib.XInternAtom(self.display, name.encode(), 1) for name in FOCUS_NAMES}
        self.lib.XSelectInput(self.display, self.root, 1 << 22)  # PropertyChangeMask
        self.lib.XFlush(self.display)
        self.fd = self.lib.XConnectionNumber(self.display)
        if not dry_run:
            name = C.util.find_library("Xtst")
            if not name:
                self.close()
                raise BridgeError("libXtst is unavailable")
            self.xtst = C.CDLL(name)
            self.xtst.XTestQueryExtension.argtypes = [C.c_void_p] + [C.POINTER(C.c_int)] * 4
            self.xtst.XTestQueryExtension.restype = C.c_int
            args = [C.c_int() for _ in range(4)]
            if not self.xtst.XTestQueryExtension(self.display, *(C.byref(x) for x in args)):
                self.close()
                raise BridgeError("XTEST is unavailable on the Steam display")
            self.xtst.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
            self.xtst.XTestFakeMotionEvent.restype = C.c_int
            self.xtst.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
            self.xtst.XTestFakeButtonEvent.restype = C.c_int

    def size(self):
        return (self.lib.XDisplayWidth(self.display, self.screen),
                self.lib.XDisplayHeight(self.display, self.screen))

    def read(self, name):
        atom = self.atoms.get(name, 0)
        if not atom or not self.cardinal:
            return None
        actual_type, fmt, count, remaining = C.c_ulong(), C.c_int(), C.c_ulong(), C.c_ulong()
        data = C.POINTER(C.c_ubyte)()
        try:
            status = self.lib.XGetWindowProperty(self.display, self.root, atom, 0, 2, 0,
                self.cardinal, C.byref(actual_type), C.byref(fmt), C.byref(count),
                C.byref(remaining), C.byref(data))
            if status != 0 or remaining.value:
                return None
            return decode_cardinals(actual_type.value, fmt.value, count.value, data, self.cardinal)
        finally:
            if data:
                self.lib.XFree(data)

    def changed(self):
        changed = False
        while self.lib.XPending(self.display):
            event = XEvent()
            self.lib.XNextEvent(self.display, C.byref(event))
            if event.type == 28 and event.property.atom in self.atoms.values():
                changed = True
        return changed

    def motion(self, x, y):
        if not self.dry_run:
            if not self.xtst.XTestFakeMotionEvent(self.display, self.screen, x, y, 0):
                raise BridgeError("XTEST motion failed")
            self.lib.XFlush(self.display)

    def button(self, down):
        if down and (self.pre_press is None or not self.pre_press()):
            return False
        if not self.dry_run:
            if not self.xtst.XTestFakeButtonEvent(self.display, 1, int(down), 0):
                raise BridgeError("XTEST button failed")
            self.lib.XSync(self.display, 0)
        return True

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None


@dataclasses.dataclass
class SteamSession:
    pid: int
    display: str
    environment: dict


def steam_session(pid=None, display=None, proc=Path("/proc")):
    if pid is None:
        candidates = []
        for entry in proc.iterdir():
            if entry.name.isdigit():
                try:
                    if (entry / "comm").read_text().strip() == "steam" and entry.stat().st_uid == os.getuid():
                        candidates.append(int(entry.name))
                except (FileNotFoundError, PermissionError):
                    continue
        if len(candidates) != 1:
            raise BridgeError("need exactly one current-user Steam process; use --steam-pid")
        pid = candidates[0]
    try:
        entry = proc / str(pid)
        if entry.stat().st_uid != os.getuid() or (entry / "comm").read_text().strip() != "steam":
            raise BridgeError("Steam PID must be the current user's steam process")
        env = dict(item.decode(errors="surrogateescape").split("=", 1)
                   for item in (entry / "environ").read_bytes().split(b"\0") if b"=" in item)
    except OSError as exc:
        raise BridgeError("cannot read Steam process environment") from exc
    discovered = env.get("DISPLAY", "")
    if not re.fullmatch(r":\d+(?:\.0)?", discovered):
        raise BridgeError("Steam DISPLAY must name a local X screen 0")
    if display is not None and display != discovered:
        raise BridgeError("--display must match the current Steam process DISPLAY")
    if env.get("XDG_CURRENT_DESKTOP", "").lower() != "gamescope":
        raise BridgeError("Steam is not running in a Gamescope session")
    return SteamSession(pid, discovered, env)


def gamescope_process_valid(pid, proc=Path("/proc"), executable=Path("/usr/bin/gamescope")):
    try:
        entry = proc / str(pid)
        if (pid <= 0 or entry.stat().st_uid != os.getuid() or
                (entry / "comm").read_text().strip() != "gamescope-wl"):
            return False
        expected = executable.resolve(strict=True)
        actual = (entry / "exe").resolve(strict=True)
        if actual != expected or not (entry / "exe").samefile(expected):
            return False
        with (entry / "exe").open("rb") as file:
            return file.read(4) == b"\x7fELF"
    except (OSError, RuntimeError):
        return False


def find_pen(device, sys_input=Path("/sys/class/input")):
    if device == "auto":
        candidates = []
        for entry in sorted(sys_input.glob("event*")):
            try:
                if (entry / "device" / "name").read_text().strip() == DEVICE_NAME:
                    candidates.append(Path("/dev/input") / entry.name)
            except OSError:
                continue
        if len(candidates) != 1:
            raise BridgeError("need exactly one Novatek NT36532E Pen event device")
        return candidates[0]
    if not re.fullmatch(r"/dev/input/event\d+", device):
        raise BridgeError("--device must be auto or an exact /dev/input/eventN path")
    path = Path(device)
    try:
        name = (sys_input / path.name / "device" / "name").read_text().strip()
    except OSError as exc:
        raise BridgeError("cannot verify input device name") from exc
    if name != DEVICE_NAME:
        raise BridgeError("input device name is not the exact Novatek pen name")
    return path


def read_ioctl(fd, number, size):
    data = bytearray(size)
    fcntl.ioctl(fd, (2 << 30) | (size << 16) | (ord("E") << 8) | number, data, True)
    return data


def open_pen(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise BridgeError("pen input must be a character device")
        name = read_ioctl(fd, 0x06, 256).split(b"\0", 1)[0].decode()
        if name != DEVICE_NAME:
            raise BridgeError("opened input device name changed")
        for axis, maximum in [(ABS_X, X_MAX), (ABS_Y, Y_MAX)]:
            values = struct.unpack("@iiiiii", read_ioctl(fd, 0x40 + axis, 24))
            if values[1:3] != (0, maximum):
                raise BridgeError("pen ABS ranges do not match this bridge")
        keys = read_ioctl(fd, 0x18, 96)
        pressed = lambda code: bool(keys[code // 8] & (1 << (code % 8)))
        return fd, pressed(BTN_TOUCH), pressed(BTN_TOOL_PEN)
    except BaseException:
        os.close(fd)
        raise


def run(args):
    session = steam_session(args.steam_pid, args.display)
    # Use Steam's own auth path unless the operator passes an explicit override.
    auth = args.xauthority if args.xauthority is not None else session.environment.get("XAUTHORITY")
    if auth is not None:
        os.environ["XAUTHORITY"] = auth
    else:
        os.environ.pop("XAUTHORITY", None)
    x11 = None
    fd = None
    bridge = None
    stopped = False
    stop_reason = "duration"
    previous_signals = {}
    def stop(signum, frame):
        nonlocal stopped, stop_reason
        stopped, stop_reason = True, "signal"
    try:
        x11 = X11(session.display, args.dry_run)
        server_id, gamescope_pid = x11.read("GAMESCOPE_XWAYLAND_SERVER_ID"), x11.read("GAMESCOPE_PID")
        if server_id != (0,) or not gamescope_pid or len(gamescope_pid) != 1 or gamescope_pid[0] <= 0:
            raise BridgeError("Steam X root is not Gamescope primary server 0")
        gamescope_pid = gamescope_pid[0]
        if not gamescope_process_valid(gamescope_pid):
            raise BridgeError("Gamescope root PID is not a current-user gamescope process")
        def current_gate():
            return gamescope_process_valid(gamescope_pid) and focus_allowed(x11.read, gamescope_pid)
        # Read the gate again immediately before the XTEST button-down request.
        x11.pre_press = lambda: not x11.changed() and current_gate()
        width, height = x11.size()
        if width < 1 or height < 1:
            raise BridgeError("invalid Steam X screen size")
        device = find_pen(args.device)
        fd, tip, proximity = open_pen(device)
        bridge = Bridge(x11, width, height, args.rotation, tip, proximity)
        bridge.set_gate(current_gate())
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_signals[sig] = signal.signal(sig, stop)
        log("start", dry_run=args.dry_run, steam_pid=session.pid, display=session.display,
            server_id=0, width=width, height=height, rotation=args.rotation,
            device=str(device), gate=bridge.gate, duration=args.duration,
            aspect_ratio_error=round(abs((X_MAX + 1) / (Y_MAX + 1) - width / height), 6))
        parser = EventParser()
        start = time.monotonic()
        next_log = start + 5
        while not stopped:
            now = time.monotonic()
            if args.duration and now - start >= args.duration:
                break
            bridge.tick(now)
            # Even a transient property notification blocks the current stroke.
            if x11.changed():
                bridge.set_gate(False)
            gate = current_gate()
            if gate != bridge.gate:
                log("gate", enabled=gate)
            bridge.set_gate(gate)
            if x11.size() != (width, height):
                raise BridgeError("Steam screen size changed; restart after mapping check")
            if now >= next_log:
                log("counts", **bridge.counts)
                next_log = now + 5
            wait = min(0.02, max(0, args.duration - (now - start))) if args.duration else 0.02
            if bridge.pressed and bridge.last_report is not None:
                wait = min(wait, max(0, bridge.last_report + 1.0 - time.monotonic()))
            ready, _, _ = select.select([fd, x11.fd], [], [], wait)
            bridge.tick(time.monotonic())
            if stopped or fd not in ready:
                continue
            try:
                data = os.read(fd, INPUT_EVENT.size * 64)
            except BlockingIOError:
                continue
            if not data:
                raise BridgeError("pen input closed")
            for kind, code, value in parser.feed(data):
                if stopped:
                    break
                if kind == EV_SYN and code == SYN_REPORT:
                    if x11.changed():
                        bridge.set_gate(False)
                    bridge.set_gate(current_gate())
                bridge.event(kind, code, value, time.monotonic())
        return 0
    finally:
        try:
            if bridge is not None:
                bridge.release("shutdown")
                log("stop", reason=stop_reason, dry_run=args.dry_run, **bridge.counts)
        finally:
            if fd is not None:
                os.close(fd)
            if x11 is not None:
                x11.close()
            for sig, handler in previous_signals.items():
                signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="read and count; never load or call XTEST")
    parser.add_argument("--duration", type=float, default=20, help="run seconds (default 20; 0 runs until a signal)")
    parser.add_argument("--device", default="auto", help="auto or a verified /dev/input/eventN path")
    parser.add_argument("--steam-pid", type=int, help="current user's exact steam PID; otherwise discover it")
    parser.add_argument("--display", help="must match the Steam process DISPLAY")
    parser.add_argument("--xauthority", help="optional X authority path; never printed")
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=0,
                        help="clockwise pen-to-screen rotation (default 0)")
    args = parser.parse_args(argv)
    if not 0 <= args.duration <= 86400:
        parser.error("--duration must be between 0 and 86400 seconds")
    try:
        return run(args)
    except (BridgeError, OSError) as exc:
        log("error", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
