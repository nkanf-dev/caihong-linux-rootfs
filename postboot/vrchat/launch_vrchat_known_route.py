#!/usr/bin/env python3
"""Route only VRChat's original Armada chain through its private FEX copy.

Adapted from the verified launch_vrchat_known_route.py. No Steam configuration,
stock tool, game, EAC binary, or prefix content is edited by this launcher.
"""
import json
import os
from pathlib import Path
import stat
import sys

APP_ID = "438100"
ARMADA_LAUNCHER = "/usr/libexec/armada/armada-game-launch"
PRIVATE_NAME = "caihong-vrchat-fex-eac-tool"
EXPERIMENTAL = ("FEX_NEEDSSECCOMP", "FEX_HIDEHYPERVISORBIT", "FEX_HOSTFEATURES")


def owner_directory(path, uid, *, create=False):
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        raise RuntimeError("A private route directory is not an owner-controlled directory")
    if info.st_mode & 0o077:
        raise RuntimeError("A private route directory must have mode 0700")


def launch(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    home = Path.home()
    uid = os.getuid()
    if uid == 0:
        raise RuntimeError("Run from the non-root Steam desktop session")
    steam = home / ".local/share/Steam"
    old = str(steam / "steamapps/common/FEX-Emu/fex-compat-tool")
    private = home / ".local/share" / PRIVATE_NAME
    new = str(private / "fex-compat-tool")
    prefix = home / ".local/share/cvrc-x64"
    matches = [index for index, argument in enumerate(args) if argument == old]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one stock Steam FEX wrapper; no launch performed")
    if os.environ.get("SteamAppId") != APP_ID:
        raise RuntimeError("This launcher is restricted to VRChat (438100)")
    if os.environ.get("STEAM_COMPAT_DATA_PATH") != str(prefix):
        raise RuntimeError("VRChat must select the private HOME/.local/share/cvrc-x64 prefix")
    for key in EXPERIMENTAL:
        if os.environ.get(key):
            raise RuntimeError("Unexpected experimental FEX option: " + key)
    if not prefix.is_dir():
        raise RuntimeError("The private x86-64 prefix directory is missing")
    for path in (Path(old), Path(new), Path(ARMADA_LAUNCHER)):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError("A required original-chain executable is missing or not executable")
    runtime_root = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"))
    if not runtime_root.is_absolute():
        raise RuntimeError("XDG_RUNTIME_DIR must be an absolute owner-controlled directory")
    owner_directory(runtime_root, uid)
    runtime = runtime_root / "cvrc-fex"
    # Steam-mode FEX selects this filesystem socket through APP_DATA_LOCATION.
    socket = runtime / "data/Server" / f"{uid}.FEXServer.Socket"
    if len(os.fsencode(socket)) >= 108:
        raise RuntimeError("The private FEX server socket path is too long")
    owner_directory(runtime, uid, create=True)
    state = home / ".local/state/caihong-vrchat-logs/x64-known-route"
    owner_directory(state, uid, create=True)
    args[matches[0]] = new
    paths = [path for path in os.environ.get("STEAM_COMPAT_TOOL_PATHS", "").split(":") if path]
    if str(private) not in paths:
        paths.append(str(private))
    os.environ["FEX_APP_DATA_LOCATION"] = str(runtime / "data") + "/"
    os.environ["FEX_APP_CACHE_LOCATION"] = str(prefix / "fex-cache") + "/"
    os.environ["STEAM_COMPAT_TOOL_PATHS"] = ":".join(paths)
    os.environ.pop("PROTON_LOG", None)
    os.environ.pop("PROTON_LOG_DIR", None)
    # Do not record argv or the inherited environment: either can carry private data.
    record = {"appid": APP_ID, "old_wrapper_matches": 1,
              "private_wrapper": new, "prefix": str(prefix),
              "server_data": os.environ["FEX_APP_DATA_LOCATION"],
              "stock_tool_changed": False,
              "event": "private route prepared; exec follows"}
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(state / "launch-routing.json", flags, 0o600)
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output, indent=2)
        output.write("\n")
    os.execv(ARMADA_LAUNCHER, [ARMADA_LAUNCHER] + args)


def main():
    try:
        launch()
    except (OSError, RuntimeError) as error:
        # Do not include arbitrary argv, environment values, or filesystem exceptions.
        message = str(error) if isinstance(error, RuntimeError) else "Private route filesystem or exec check failed"
        print("VRChat private route: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
