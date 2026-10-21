#!/usr/bin/env python3
"""App-scoped Steam VRChat mode selection and bounded one-start orchestration."""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys

APP_ID = "438100"
PRIVATE_NAME = "caihong-vrchat-fex-eac-tool"
EXPERIMENTAL = ("FEX_NEEDSSECCOMP", "FEX_HIDEHYPERVISORBIT", "FEX_HOSTFEATURES")

class LaunchError(RuntimeError):
    """A fixed, safe-to-log launch diagnostic (never arbitrary argv)."""

@dataclass(frozen=True)
class Snapshot:
    processes: tuple = ()  # (pid, exact role, Linux start tick)
    crash_marker: bool = False
    alvr_blocked: bool = False
    trusted_client: bool = True
    collision: bool = False
    driver_loaded: bool = False
    monitor_ready: bool = False
    fresh_stream: bool = False
    receipt_consumed: bool = False
    starting: bool = False

    @property
    def healthy(self):
        roles = {p[1] for p in self.processes}
        return (roles >= {"vrserver", "vrcompositor", "vrmonitor"} and
                self.driver_loaded and self.monitor_ready and self.fresh_stream)

def select_mode(args, mode="auto"):
    if mode not in ("auto", "vr", "desktop"):
        raise LaunchError("Unknown launch mode")
    count = args.count("--no-vr")
    if count > 1 or any(a.startswith("--no-vr=") for a in args):
        raise LaunchError("Ambiguous desktop mode arguments; restore Steam's original launch choice")
    if "--vr" in args or "-vr" in args:
        raise LaunchError("Unexpected VR override; use Steam's original VRChat launch choices")
    if mode == "vr" and count:
        raise LaunchError("VR mode conflicts with Steam's desktop argument")
    return ("desktop" if count else "vr") if mode == "auto" else mode

def _private(path, *, directory=False):
    try:
        info = path.lstat()
    except OSError:
        raise LaunchError("The private VRChat tool or prefix is missing") from None
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise LaunchError("The private VRChat tool and prefix must be owner-controlled real paths")
    if not directory and not os.access(path, os.X_OK):
        raise LaunchError("The private VRChat tool is not executable")

def validate_command(args, env, *, home=None):
    home = Path.home() if home is None else home
    prefix = home / ".local/share/cvrc-x64"
    stock = home / ".local/share/Steam/steamapps/common/FEX-Emu/fex-compat-tool"
    private = home / ".local/share" / PRIVATE_NAME
    if env.get("SteamAppId") != APP_ID:
        raise LaunchError("This launcher accepts only Steam VRChat app 438100")
    if env.get("STEAM_COMPAT_DATA_PATH") != str(prefix):
        raise LaunchError("VRChat must select the existing private cvrc-x64 prefix")
    if args.count(str(stock)) != 1:
        raise LaunchError("Expected exactly one original stock FEX compatibility wrapper")
    launchers = [a for a in args if a.replace("\\", "/").rsplit("/", 1)[-1].lower() == "launch.exe"]
    if len(launchers) != 1:
        raise LaunchError("Expected the original EAC launch.exe command; do not launch VRChat.exe directly")
    if any(env.get(key) for key in EXPERIMENTAL):
        raise LaunchError("Unexpected experimental FEX options; restore the protected VRChat route")
    _private(prefix, directory=True)
    _private(private, directory=True)
    _private(private / "fex-compat-tool")
    if not stock.is_file() or not os.access(stock, os.X_OK):
        raise LaunchError("The original stock FEX compatibility wrapper is missing")

def steam_environment(source):
    """Native Steam receives its normal desktop session, not the game's private route."""
    allowed = {"HOME", "USER", "LOGNAME", "PATH", "LANG", "LANGUAGE", "TZ", "DISPLAY",
               "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
               "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
               "PULSE_SERVER", "PIPEWIRE_RUNTIME_DIR", "PULSE_RUNTIME_PATH", "TERM"}
    return {k: v for k, v in source.items() if k in allowed or k.startswith("LC_")}

def _safe(snapshot):
    if snapshot.crash_marker:
        raise LaunchError("SteamVR crash marker found. Close SteamVR, review the saved failure, and use the reviewed retry gate")
    if snapshot.alvr_blocked:
        raise LaunchError("ALVR is blocked or its safe-mode state is unknown. Review the failure and use the reviewed retry gate")
    if snapshot.collision:
        raise LaunchError("Multiple runtime instances or an existing VRChat game were found. Close them normally; nothing was stopped")
    if not snapshot.trusted_client:
        raise LaunchError("No trusted ALVR headset is configured. Pair the intended headset in ALVR before VR launch")

def ensure_vr(runtime, *, timeout=90.0):
    """One request, no restart or process termination. runtime.wait is deadline-bound."""
    if not 0 < timeout <= 180:
        raise LaunchError("Readiness deadline must be between zero and 180 seconds")
    deadline = runtime.monotonic() + timeout
    try:
        first = runtime.inspect()
        _safe(first)
        cold = not first.processes and not first.starting
        if first.healthy:
            runtime.record("runtime-reused")
            return "reused"
        identity = {p for p in first.processes if p[1] in ("vrserver", "vrcompositor", "vrmonitor")}
        if cold:
            # A Steam auto-start may win the race between inspect and prepare.
            if runtime.prepare() is not False:
                runtime.start()
                runtime.record("runtime-start-requested")
            else:
                cold = False
        while runtime.monotonic() < deadline:
            runtime.wait(min(0.5, max(0, deadline - runtime.monotonic())))
            current = runtime.inspect()
            _safe(current)
            observed = {p for p in current.processes if p[1] in ("vrserver", "vrcompositor", "vrmonitor")}
            if identity and not identity.issubset(observed):
                raise LaunchError("The active runtime changed or exited. Review the failure before another attempt")
            identity |= observed
            if current.healthy and (not cold or current.receipt_consumed):
                runtime.record("runtime-ready", cold_start=cold)
                return "started" if cold else "reused"
        raise LaunchError("VR readiness deadline reached. Open ALVR on the trusted headset and wear it; inspect launcher status before retry")
    except (LaunchError, OSError, ValueError):
        runtime.record("failed", action="Open ALVR and wear the headset. For a crash or safe-mode block, close SteamVR normally and review the failure before using retry_gate.py")
        raise

def dispatch(args, env, mode, runtime_factory, execute, *, validate=validate_command, timeout=90.0):
    selected = select_mode(args, mode)
    validate(args, env)
    original = list(args)
    if selected == "desktop":
        if "--no-vr" not in original:
            original.append("--no-vr")
        return execute(original, env)
    runtime = runtime_factory()
    with runtime:
        ensure_vr(runtime, timeout=timeout)
        return execute(original, env)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "vr", "desktop"), default="auto")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    args = options.command[1:] if options.command[:1] == ["--"] else options.command
    try:
        if os.getuid() == 0 or not sys.platform.startswith("linux"):
            raise LaunchError("Run from the non-root Linux Steam desktop session")
        if not args:
            raise LaunchError("The original Steam %command% is required")
        # Lazy import is intentional: desktop never reads runtime files or APIs.
        def backend():
            from runtime_backend import Runtime
            return Runtime(dict(os.environ))
        def execute(original, env):
            route = Path(__file__).resolve().parent / "vrchat/launch_vrchat_known_route.py"
            if not route.is_file():
                # Source checkout layout, useful for controlled fixture testing.
                route = Path(__file__).resolve().parents[1] / "vrchat/launch_vrchat_known_route.py"
            if not route.is_file():
                raise LaunchError("The preserved private-route launcher is missing; reinstall the launcher bundle")
            os.execve(sys.executable, [sys.executable, str(route)] + original, env)
        dispatch(args, dict(os.environ), options.mode, backend, execute, timeout=options.timeout)
    except (LaunchError, OSError, ValueError):
        # Never render arbitrary exception text, argv, environment, or session data.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, LaunchError) else "A runtime prerequisite failed. Inspect the private launcher status and existing SteamVR logs"
        print("VRChat launch: " + message, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
