# Wi-Fi backend recovery

This folder covers one specific failure: NetworkManager selects `iwd`, but this Armada installation only has `wpa_supplicant`.

## Read the state first

Run on the native Linux system:

```sh
sudo python3 repair_missing_wifi_backend.py
```

The default prints a JSON plan. It does not edit files or restart services.

The repair is eligible only when all these checks pass:

- The effective NetworkManager backend is `iwd`.
- The existing Valve config contains exactly one `[device]` assignment to `iwd`.
- The iwd systemd unit, standard binary paths, and D-Bus activation file are absent.
- The wpa_supplicant unit is loaded, is not masked, and has its D-Bus activation file.
- NetworkManager is loaded and is not starting or stopping.
- The config is a root-owned regular file with one hard link and no writable group/other permissions. Its path has no symlinks.

## Apply the bounded repair

```sh
sudo python3 repair_missing_wifi_backend.py --apply
```

`--apply` requires native Linux root. The tool:

1. Rechecks the file and service state.
2. Saves the original file under `/var/lib/caihong/wifi-backend-backups/`. The directory mode is `0700`; backup files use `0600`.
3. Changes only `wifi.backend=iwd` to `wifi.backend=wpa_supplicant`. It preserves comments, line endings, powersave, unrelated settings, permissions, ownership, and Linux extended attributes, including the SELinux label.
4. Atomically replaces the file and checks NetworkManager's effective config.
5. Restarts NetworkManager once if it was active. Otherwise, it starts it once.

If the backend is already wpa_supplicant, the tool performs no write and no service action. It does not repair an unrelated stopped service in that case.

The tool rechecks file bytes and metadata after creating the backup and before replacement. Another root writer can still change the file between the final check and replacement; this manual operation requires a quiet maintenance window. It does not provide a compare-and-swap lock shared with SteamOS-manager or other root writers.

If the effective-config check fails before a service action, the tool restores its own unchanged replacement from memory. If a service operation fails, it keeps the corrected config and private backup. It reports the error without retries. Review the journal before another service action.

The tool does not alter network profiles, MAC policy, firmware, drivers, Steam settings, or polkit policy. It does not install iwd. It is a manual repair tool, not a boot or session hook.

## Verify discovery and the existing connection

```sh
systemctl is-active NetworkManager wpa_supplicant
NetworkManager --print-config
nmcli -f DEVICE,TYPE,STATE,CONNECTION device
nmcli -f GENERAL.STATE,GENERAL.REASON,WIFI-PROPERTIES device show wlp1s0
nmcli -f IN-USE,SSID,SIGNAL,SECURITY device wifi list --rescan no
```

Check the Wi-Fi list in Steam as well. Confirm the saved network reconnects. Use the normal Desktop → Game Mode path and compare the backend file before and after each switch.

## Why the SteamOS-manager method is not used for recovery

The replaced Terra `steamos-manager-26.4.1-2.fc44` exposes `RootManager.SetWifiBackend(u)` with 0=iwd and 1=wpa_supplicant. Its implementation writes the config, stops NetworkManager, then disables/stops the opposite backend. If `iwd.service` is absent, the call fails after it has stopped NetworkManager. This happened on the device. A single NetworkManager start with the corrected config recovered discovery and the saved connection.

Older shell-helper and Manager-property API instructions do not apply to this installed version.

## Prevent Steam from selecting the missing backend again

A correct default config is necessary, but an unpatched SteamOS-manager can still accept Steam's later request for iwd. Armada's own `0011-wifi-Always-write-wpa_supplicant-as-the-backend.patch` pins this installation to its supported backend and returns early when it is already selected. See:

- [Armada patch manifest](https://github.com/armada-os/armada/blob/HEAD/packages/steamos-manager/PATCHES.md)
- [Armada WPA backend patch](https://github.com/armada-os/armada/blob/HEAD/packages/steamos-manager/patches/0011-wifi-Always-write-wpa_supplicant-as-the-backend.patch)
- [SteamOS-manager v26.4.1 Wi-Fi implementation](https://github.com/evlaV/steamos-manager/blob/v26.4.1/steamos-manager/src/wifi.rs)

Restore a matching Armada-patched package through the normal package workflow if Steam resets this file. Keep the board-specific package from being replaced by a newer-release generic Terra package. Do not add a polling service or repeated NetworkManager restart hook.

The image overlay selects wpa_supplicant and retains the existing `wifi.powersave=3`. The Armada image verifier checks the selected backend and wpa_supplicant's service/activation files.

## Host-only tests

From the repository root:

```sh
python3 -m unittest discover -s postboot/network -p 'test_*.py' -v
bash -n scripts/verify-armada-rootfs.sh
```

The unit tests use temporary config files and fake command responses. They do not contact a device or run systemctl.

## Package and image safeguards

- [Exact package holds](locks/README.md) preserves the reviewed 39-name board policy and existing DNF settings.
- [Original-payload repack sources](restoration/README.md) records the three restored package payloads and provenance.
- `image/assert_custom_package_baseline.py` captures the original custom package identity before image-builder DNF operations, rejects replacements before image output, and merges the hold policy without replacing upstream DNF defaults. It reports incompatible camera development dependencies for a matching-devel or isolated-builder fix.
- [Current acceptance](../docs/current-validation.md#native-package-recovery-and-wi-fi-mode-switch-acceptance) records the three restored packages, actual mode-switch/scan/reconnect checks, and remaining Mesa scope.
