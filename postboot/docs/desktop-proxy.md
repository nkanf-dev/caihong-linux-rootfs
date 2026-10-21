# Desktop, controller, pen, and HK proxy

This directory preserves the custom post-boot fixes from the local Caihong assessment.
It does not alter the kernel build or install a root filesystem image.
Run the setup commands on the Linux device only when you choose to apply the fix.
Run user commands as the Steam user. Use `sudo` only where shown.
`$HOME` always means that user's home, not root's home.

## Recorded device state

The source records are `installation/CONTINUATION.json`, `installation/kde-menu-status.json`,
`installation/peripheral-status.json`, `proxy-install/verification-summary.json`, and the custom pen implementation.
These are historical observations, not a new device inspection.

| Item | Recorded result |
| --- | --- |
| Native Steam power menu | `show_switch_to_desktop_at_login` changed from false to true through the official setter. Readback survived a Steam CEF reload. The native dialog contained Switch to Desktop. The actual Plasma transition was not exercised in that check. |
| Menu cause | OOBE was already complete and Steam had a current user. The source gate already allowed a desktop item through the current-user condition. The older missing item has no established cause. |
| Controller | The paired Xbox controller was bonded, trusted, connected, and exposed both physical and Steam virtual gamepad input. Battery readback was 52%. |
| Pen | The user confirmed normal SteamUI input. A 35-second live bridge run recorded 13 presses, 13 releases, and 1,898 motions. The user unit was enabled and active before the display-manager restart. Starting it automatically in a fresh Gamescope session remained to be checked. |
| Decky | Native ARM64 Decky Loader 3.3.0 and DeckyClash 1.3.5 were installed. Existing Armada plugins were retained. The native Mihomo core reported 1.19.31. |
| HK routing | Global mode and the selected HK node carried direct public TCP, Steam/CDN connections, DNS fake-IP handling, and UDP STUN. No Steam-download direct exception was enabled. |
| Proxy lifecycle | Stop removed the TUN/policy rules and restored network access. Restart recreated TUN, retained HK selection, and returned a successful Steam HTTP check. Decky service and plugin autostart were enabled in the saved final proxy record. |
| Steam download region | The record changed region 160 to 33, label `中国-香港`. Configured value 33 was read back; applying it to a new Steam session was still pending in that record. Account country was unchanged. |

## 1. Native Switch to Desktop menu

`desktop/steam-native-desktop-menu.js` contains only the native setting action.
Load its text into the **main SteamUI page** developer console using a locally controlled session.
It does not connect to a debug port or discover browser targets.
Do not expose Steam's debugging interface on the network.

```js
await nativeDesktopMenu("read");
await nativeDesktopMenu("enable");
```

Close the existing power menu with Cancel or Escape, then reopen it:

```js
await nativeDesktopMenu("open");
```

The Steam source also requires Gamescope, a completed OOBE, no kiosk/lock screen, and no VR UI.
Check those conditions if the native item is still missing.
Select the native Switch to Desktop item when ready, then confirm Plasma appears.
The helper never triggers the desktop transition itself.

Rollback, if the original setting was false:

```js
await nativeDesktopMenu("disable");
```

The setting setter calls Steam's settings API. No `config.vdf`, OS identity, source patch,
Decky menu injection, OOBE flags, or account files need to be changed.
Armada's `os-session-select` maps desktop/plasma to `steamosctl switch-to-desktop-mode`.
Its `set-default-desktop-session` command chooses the Plasma variant; it is not the mode-switch action.

## 2. SteamUI pen bridge

`desktop/pen_steamui_bridge.py` is the actual custom bridge, retained with its 28 pure tests.
It reads exactly `Novatek NT36532E Pen` with ABS ranges X `0..29999`, Y `0..21199`.
It discovers Steam's display and X authority from the current user's Steam process.
It never prints authority cookies, grabs the tablet, opens `uinput`, or changes input permissions.
Linux Python 3.9+, libX11, libXtst, and read access to that pen event device are required.

Output requires Gamescope server 0, a current-user `gamescope-wl` process whose executable is
`/usr/bin/gamescope`, a nonzero focused window, and both focused app IDs equal to 769.
The gate is checked again before each button-down.
A new click also requires fresh X/Y coordinates and a lifted pen since the last blocked stroke.
Gate loss, proximity loss, dropped input, timeout, signals, and exit release the bridge's left button.
The original tablet stream remains available to KDE, including pressure.
XTEST targets the verified display; a focus change can occur between the last gate check and event handling.
Use the bounded focus check below before enabling the unit.

From the repository root, as the Steam user:

```sh
python3 postboot/desktop/pen_steamui_bridge.py --dry-run --duration 20 --device auto --rotation 0
python3 postboot/desktop/pen_steamui_bridge.py --duration 20 --device auto --rotation 0
```

Start with the pen lifted. Check all four corners and the center at the actual display size.
For the recorded 3000×2120 screen, the corners map to `(0,0)`, `(2999,0)`, `(0,2119)`, `(2999,2119)`.
Tap a harmless SteamUI control. Switch focus to a game and confirm pointer injection stops.
Return to SteamUI, lift the pen, and check that tapping works again.
Use `--rotation 90`, `180`, or `270` only after checking physical orientation.
Stop with Ctrl-C. Run only one bridge instance.

Install only after the bounded checks:

```sh
install -d -m 700 "$HOME/.local/bin" "$HOME/.config/systemd/user"
test ! -e "$HOME/.local/bin/pen-steamui-bridge.py"
test ! -e "$HOME/.config/systemd/user/pen-steamui-bridge.service"
install -m 700 postboot/desktop/pen_steamui_bridge.py "$HOME/.local/bin/pen-steamui-bridge.py"
install -m 600 postboot/desktop/pen-steamui-bridge.service "$HOME/.config/systemd/user/pen-steamui-bridge.service"
systemctl --user daemon-reload
systemctl --user enable pen-steamui-bridge.service
systemctl --user is-active gamescope-session-plus@steam.service
systemctl --user start pen-steamui-bridge.service
systemctl --user status pen-steamui-bridge.service
```

Do not continue past a failed `test` or inactive Gamescope target.
The unit uses `%h`, belongs to the Gamescope session service, and stops with that session.
No fixed UID, root service, lingering user session, or display-manager restart is required.
After the next normal Gamescope login, verify the user unit starts and repeat a short tap check.
After switching to KDE, verify the bridge stops and native pen pressure still works.

Rollback:

```sh
systemctl --user disable --now pen-steamui-bridge.service
rm -- "$HOME/.config/systemd/user/pen-steamui-bridge.service" "$HOME/.local/bin/pen-steamui-bridge.py"
systemctl --user daemon-reload
```

Remove only the two installed files. The unit creates no global input rule.

## 3. Paired controller trust and reconnect

Power on the already-paired controller. Find its address privately in Bluetooth settings.
The helper accepts one address, checks that it is already paired, and then uses only
`bluetoothctl info`, `trust`, `connect`, or explicit rollback `untrust`.
It does not scan, pair, remove a bond, reset an adapter, save an address, or print raw tool output.

```sh
python3 postboot/desktop/controller-trust.py check REPLACE_CONTROLLER_ADDRESS
python3 postboot/desktop/controller-trust.py repair REPLACE_CONTROLLER_ADDRESS
```

Read the JSON booleans, then check Steam's controller test and real button/axis input.
Confirm reconnect after powering the controller off and on.
Only if it was originally untrusted, undo the new trust flag with:

```sh
python3 postboot/desktop/controller-trust.py untrust REPLACE_CONTROLLER_ADDRESS
```

## 4. Decky/Mihomo policy-TUN compatibility

Use `proxy/README.md` for the proxy setup and rollback sequence.
The preserved switches disable NFT auto-redirect on the assessed kernel, retain policy TUN,
keep the controller on authenticated loopback, and disable the Steam-download direct exception.
No kernel, router, Android, or global host-proxy changes are part of this fix.

Set Steam **Settings → Downloads → Download Region → China - Hong Kong** (`中国-香港`).
Restart Steam normally when ready and confirm the selected region remains visible.
The download region is separate from the subscription node and Steam account country.
Do not copy account VDF files into this repository.

## Host validation of this preservation

From the repository root:

```sh
python3 -B -m unittest discover -s postboot/desktop -p 'test_*.py' -v
python3 -B -m unittest discover -s postboot/proxy -p 'test_*.py' -v
node --check postboot/desktop/steam-native-desktop-menu.js
node --test postboot/desktop/test-steam-native-menu.cjs
```

The preserved bridge has pure behavior tests. The new helpers have mocked/local unit checks,
CLI parsing checks, and syntax checks. Installation, systemd unit execution, Bluetooth actions,
controller API calls, and routing changes were not run during host-only preservation.
The device observations above come from the saved assessment records.
