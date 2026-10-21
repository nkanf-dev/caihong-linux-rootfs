# Return to Android in the power menu

This Decky plugin adds **返回 Android** to the native Steam GamepadUI power menu. The existing **Switch to Desktop** action stays native and unchanged.

Selecting the new item runs read-only checks and opens a separate confirmation. **取消** has initial focus. The confirmation asks the user to save progress and close games. Only **重启并返回 Android** consumes a 45-second single-use confirmation and requests the switch. The plugin never closes a game or forces a reboot.

## Components

- `src/`: native menu hook, confirmation view, and single-use frontend session.
- `main.py`: root Decky backend using the existing Linux-side `/usr/local/sbin/caihong-slot android` launcher.
- `install.py`: file-only install/remove with a content receipt and pinned directory descriptors.
- `config.example.json`: unapproved Android A / Linux B configuration example.
- `tests/`: mock backend, filesystem installer, React view, hook, and lifecycle tests.
- `source-references.json`, `frontend-references.json`: public source provenance and exact refs.

The plugin uses Decky Loader **3.3.0**, `@decky/ui` **4.15.1**, and `@decky/api` **1.1.3**. It uses Decky's authenticated backend RPC and existing root-plugin permission. It adds no HTTP server, sudo rule, polkit rule, password, or PIN setting.

There is no dedicated Decky power-menu registration API. The hook scopes the native context-menu manager to the observed synchronous `Router.OpenPowerMenu` call. It clones the incoming React element, patches that clone with the official React tree helper, and appends a native `MenuItem` only to a native `Menu` containing the observed shutdown and restart actions. Runtime structure checks leave unknown Steam builds unchanged. It does not edit Steam files, replace the desktop action, or insert into unrelated menus. Unload removes both hooks, closes affected menus/dialogs, and cancels pending confirmation tokens.

## Host build and tests

From this directory:

```sh
npm ci
npm run typecheck
npm test
npm run build
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

`package-lock.json` pins build inputs. `node_modules/` and `dist/` are generated and ignored by Git. The installable frontend is `dist/index.js`; build it before copying the source directory to Linux. No native binary is bundled.

## Later Linux setup

Perform this section after the charging session, when the user chooses to resume device work. Run it in the existing Linux installation. Keep Steam/Decky running unchanged during the initial source copy and read-only checks.

1. In the Linux terminal, confirm the existing Decky installation reports Loader 3.3.0. Confirm the service retains its existing Armada unit and listens only on loopback. Keep `SERVER_HOST` unset or explicitly `127.0.0.1`, `::1`, or `localhost`. Do not enable remote access.
2. Inspect the existing Linux-side launcher and public boot-control tool:

   ```sh
   sudo /usr/local/sbin/caihong-slot status
   sudo /usr/local/sbin/qbootctl -c
   sudo /usr/local/sbin/qbootctl -a
   sudo /usr/local/sbin/qbootctl -b a
   sudo /usr/local/sbin/qbootctl -n a
   sudo sha256sum /usr/local/sbin/caihong-slot /usr/local/sbin/qbootctl
   ```

   Require **Current slot: _b**, **Active slot: _b**, and Android A marked **bootable** and **successful**. Independently confirm the deployment metadata identifies Android A and Linux B. Review the installed script against `source-references.json`. Record the installed `qbootctl` digest from the trusted deployment. Stop on any difference; do not substitute another slot or edit a guard to proceed.
3. Read the exact login1/busctl JSON shape before installation. The backend expects `CanReboot` string `yes`, no `shutdown` inhibitors (including delay inhibitors), `PreparingForShutdown=false`, no scheduled shutdown, no firmware/bootloader override, and `systemctl --check-inhibitors=yes is-system-running` equal to `running`. `RebootToBootLoaderMenu` is disabled at uint64 `18446744073709551615`. The parsed signatures are `s`, `a(ssssuu)`, `b`, `(st)`, `b`, `t`, and `s`. Use only `busctl --system --json=short call` / `get-property` reads on `org.freedesktop.login1` `/org/freedesktop/login1` `org.freedesktop.login1.Manager`. If the target format differs, preserve that output privately for a code review; no selection has run.
4. Verify the actual `$HOME/homebrew/plugins` directory is root-owned and not group/other writable. The installer refuses a writable namespace. It never changes ownership of existing Decky folders or touches other plugins.
5. From the built source directory, review the file-only plan:

   ```sh
   python3 install.py plan --homebrew "$HOME/homebrew"
   ```

6. Install the plugin and root-owned config only after the above checks. Keep the Steam user's expanded home in the argument, even when invoking sudo:

   ```sh
   sudo python3 install.py install --homebrew "$HOME/homebrew" \
     --loader-version 3.3.0 --approve-android-a-linux-b \
     --qbootctl-sha256 VERIFIED_QBOOTCTL_SHA256
   ```

   Replace `VERIFIED_QBOOTCTL_SHA256` with the exact digest reviewed in step 2. Existing plugin/config files cause a stop. Installation writes only `$HOME/homebrew/plugins/CaihongPowerMenu/` and `/etc/caihong-power-menu.json`. It does not load the plugin, start a service, restart Steam, select a slot, or reboot. The next normal Decky/Steam startup loads it.
7. After that normal startup, open the power menu with the controller. Verify **返回 Android** appears alongside the original native actions and **切换至桌面**. Open the Android confirmation, verify its text and cancel focus, then choose **取消**. Repeat open/cancel once. The target must remain Linux B active; no reboot should occur. Check the plugin can unload and restore the original menu.
8. Only when the user explicitly chooses a full boot test, save work and close games, reopen the confirmation, and confirm the switch. Observe Android boot. Keep Linux recovery instructions available. Do not perform this step during charging-only work.

## Backend safety checks

Loading, rendering, polling, preparing, cancelling, installing, and unloading do not select a boot slot. Preparation and confirmed execution independently check all prerequisites.

- Linux platform and Decky root-plugin context; loopback Decky host.
- Root-owned config and tool paths, no symlink ancestors or group/other write permissions.
- Explicit approved **Android A / Linux B** mapping, exact reviewed launcher and qbootctl digests.
- Boot-control **current B** and **active B**, Android A bootable and already successful.
- Normal reboot permission, no shutdown inhibitors, pending shutdown, reboot target override, or degraded startup state.
- Read-only support check for the final `--check-inhibitors=yes` option.

The confirmed path calls the supported launcher as `caihong-slot android`, without `--reboot`. That script resolves the live Linux slot and verifies the selected slot. The plugin then independently reads **active A**, **current B**, and A bootability before rechecking reboot conditions and running ordinary `systemctl --check-inhibitors=yes reboot`. It uses fixed absolute commands with bounded output, a timeout, and process-group cleanup. There is no automatic retry or slot repair.

A shutdown inhibitor can appear after selection. If the slot is already verified as A and reboot fails, the dialog says Android A remains selected for the next boot. If selection/readback fails, it says the slot may have changed. Inspect it in the desktop before another action. The plugin never changes it back automatically.

## Remove or reinstall

First close the Android dialog and unload this plugin through Decky. Stop the owning Decky session normally before file removal. Do not interrupt an already confirmed switch. Then run:

```sh
sudo python3 install.py remove --homebrew "$HOME/homebrew"
```

Removal checks the receipt, file digests, root-owned config, and root-owned plugin/dist directories. It refuses changed or extra files for inspection. It removes only this plugin and its config, not other plugins, Loader, services, Steam settings, or boot metadata. It does not restart anything. After a normal Decky/Steam start, the native power menu remains. Build and run the install steps again to reinstall. Keep Loader and package versions pinned until a reviewed source update.

## Validation state

The implementation and tests were prepared on the host. The device was not connected by this work. No device install, service restart, slot selection, or reboot occurred. `VALIDATION.md` records the checks. The later Linux setup above includes the actual API readback, visible controller open/cancel check, and a separately chosen full boot check.

## License

Original code in this directory uses the MIT license in `LICENSE`. Public Decky API dependencies are obtained by the locked build; Steam, Decky Loader, qbootctl, and the existing GPL slot launcher are not vendored. The original launcher runs as a separate existing system tool.
