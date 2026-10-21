# Host validation

Checks run from the repository root during host-only preservation:

| Check | Result |
| --- | --- |
| Preserved pen bridge pure unit suite | 28 passed |
| Controller trust helper mocked suite | 4 passed |
| Proxy helper unit suite | 8 passed, including local configure/autostart/restore with a fake YAML parser |
| Native Steam menu mocked Node suite | 3 passed |
| Python source compile checks | 7 source/test files compiled without writing bytecode |
| Four Python CLIs with `--help` | Passed |
| Native menu JavaScript `node --check` | Passed |
| Secret-free template JSON parse | Passed |
| Personal-home/source-workspace links, private IPv4, UUID, and device-address scan | No matches |

The proxy merge template was checked for the expected routing switches on the host.
The device's bundled `ruamel.yaml` was not executed during preservation.
The systemd unit is retained unchanged from the custom deployed source.
No systemd analyzer is installed on this host, so only its text and portable `%h` path were reviewed here.

No installation, service start/stop, Bluetooth action, controller API request, proxy route change,
network deployment, ADB, or SSH command was run.
Saved historical device outcomes and the remaining fresh-Gamescope start check are described in
`../docs/desktop-proxy.md`.
