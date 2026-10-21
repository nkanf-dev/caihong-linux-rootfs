#!/usr/bin/env python3
"""Read safe core status or select one HK node through authenticated IPv4 loopback."""
import argparse
import json
from pathlib import Path
import stat
import urllib.error
import urllib.request


def private_json(path):
    mode = path.stat().st_mode
    if path.is_symlink() or not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Private input must be a regular file with mode 0600")
    return json.loads(path.read_text())


class Controller:
    def __init__(self, settings):
        port = settings.get("controller_port")
        secret = settings.get("secret")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid loopback controller port")
        if not isinstance(secret, str) or not secret or secret.startswith("REPLACE_"):
            raise ValueError("Set a private controller secret first")
        if settings.get("allow_remote_access") is not False:
            raise ValueError("Disable controller remote access first")
        self.base = "http://127.0.0.1:" + str(port)
        self.headers = {"Authorization": "Bearer " + secret, "Content-Type": "application/json"}
        # Do not use ambient proxies or follow redirects with the authentication header.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, method="GET", data=None):
        payload = None if data is None else json.dumps(data).encode()
        request = urllib.request.Request(self.base + path, data=payload,
                                         headers=self.headers, method=method)
        with self.opener.open(request, timeout=15) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError("Unexpected controller response size")
            return json.loads(body) if body else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "select-hk"))
    parser.add_argument("--settings", type=Path,
                        default=Path.home() / "homebrew/settings/DeckyClash/config.json")
    parser.add_argument("--selection", type=Path, help="0600 JSON file with node: REPLACE_HK_NODE_NAME")
    args = parser.parse_args()
    api = Controller(private_json(args.settings.expanduser()))
    runtime = api.request("/configs")
    selected = None
    if args.action == "select-hk":
        if args.selection is None:
            parser.error("select-hk requires --selection")
        selected = private_json(args.selection.expanduser()).get("node")
        if not isinstance(selected, str) or not selected or selected.startswith("REPLACE_"):
            raise ValueError("Set the exact private HK node name first")
        proxies = api.request("/proxies").get("proxies", {})
        if selected not in proxies or "GLOBAL" not in proxies:
            raise ValueError("Selected node or GLOBAL group not found")
        if runtime.get("mode") != "global":
            raise ValueError("Set global mode through the saved override first")
        api.request("/proxies/GLOBAL", "PUT", {"name": selected})
    group = api.request("/proxies/GLOBAL")
    match = None if selected is None else group.get("now") == selected
    print(json.dumps({"mode": runtime.get("mode"), "tun_enabled": runtime.get("tun", {}).get("enable"),
                      "auto_route": runtime.get("tun", {}).get("auto-route"),
                      "auto_redirect": runtime.get("tun", {}).get("auto-redirect"),
                      "allow_lan": runtime.get("allow-lan"), "ipv6": runtime.get("ipv6"),
                      "selection_matches": match}, sort_keys=True))
    if selected is not None and not match:
        raise ValueError("HK selection readback failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print API bodies, proxy names, settings, tokens, or urllib error details.
        raise SystemExit("Controller action failed (" + type(error).__name__ + "). Check private inputs locally.")
