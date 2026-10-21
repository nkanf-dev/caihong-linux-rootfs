# Missing Wi-Fi backend recovery plan

**Goal:** recover only the confirmed NetworkManager/iwd mismatch. Keep device execution with the root operator.

**Design:** provide a Python standard-library tool. The default is a read-only JSON plan. `--apply` requires native Linux root. Repair only the existing Valve backend file when its selected backend and the effective NM backend are iwd, iwd is absent, and wpa_supplicant is available. Preserve every other byte and file mode. Back up privately, replace atomically, verify the effective result, then perform one NM restart or start. Never call SteamOS-manager's backend method. A healthy WPA state makes no write and no service action. The tool is manual recovery, not a session hook.

## Steps

- [x] Add `repair_missing_wifi_backend.py` with read-only probes and bounded repair gates.
- [x] Add host-only standard-library unit tests for dry run, symlink refusal, missing dependencies, exact replacement, private backup, rollback, healthy no-op, and one service action.
- [x] Run tests from the repository command interface and inspect the diff.
- [x] Write operator documentation and report evidence to the parent. No git or device operations.
