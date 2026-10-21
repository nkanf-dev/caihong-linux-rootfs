"""Portable paths for the app-scoped SteamVR preservation tools."""
import os
from pathlib import Path

def home():
    return Path(os.environ.get("CAIHONG_HOME", str(Path.home()))).expanduser().resolve()

def steam_root():
    return Path(os.environ.get("CAIHONG_STEAM_ROOT", str(home() / ".local/share/Steam"))).expanduser().resolve()

def state_root():
    return home() / ".local/state/caihong-pcvr"

def library_paths():
    return ["/usr/lib/pressure-vessel/overrides/lib/aarch64-linux-gnu",
            "/usr/lib/pressure-vessel/overrides/lib/aarch64-linux-gnu/aliases",
            "/usr/lib64", str(steam_root() / "steamrtarm64"),
            str(steam_root() / "lib/aarch64-linux-gnu")]
