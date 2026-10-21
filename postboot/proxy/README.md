# DeckyClash HK policy-TUN repair

This is a custom compatibility fix for an existing DeckyClash 1.3.5 installation on Caihong/Armada.
It does not install or copy Decky Loader, DeckyClash, Mihomo, subscriptions, geodata, or dashboards.
Keep the existing Armada service and plugins.
Use the matching native ARM64 upstream releases listed in `PROVENANCE.md`.

## Files

- `caihong-policy-tun.yaml`: partial override, not a standalone Mihomo configuration.
- `deckyclash-local.py`: private backup and allowlisted local config edits; no service or network actions.
- `hk-controller.py`: authenticated IPv4-loopback status/readback and one exact node selection.
- `deckyclash-settings.example.json`: selected settings only, not a replacement for installed settings.
- `hk-selection.example.json`: private local node-name input template.
- `20-preserve-armada.conf`: preserves Armada's existing Decky systemd service when updating Loader.

The compatibility override keeps policy TUN with `auto-route: true` and `strict-route: true`.
It disables `auto-redirect` because the assessed kernel lacked `NFT_REDIR`.
Separate HTTP, SOCKS, redirect, and TPROXY listener ports are disabled.
DNS capture covers UDP and TCP port 53. IPv6 resolution is disabled.
`allow-lan` is false and Decky's controller remote access is false.
Global mode and `store-selected` retain the chosen node across the core lifecycle.
The merge retains existing DNS upstreams, fake-IP filters, and route exclusions.
Review local subnet exclusions privately before starting TUN.

## Prepare

Work on the device with the normal Steam user's home in `$HOME`.
If Decky is elsewhere, pass its actual homebrew root through `--homebrew`.
Do not point this at a host machine's homebrew tree.
Use a local terminal with a second local recovery terminal available.
Keep all subscription files, node selections, settings, and backups outside the checkout.
Do not use debug logging: upstream debug messages can include private settings.

1. Install the verified native ARM64 releases through the upstream process if they are not installed.
   Preserve the original Loader, version marker, service, plugins, and private settings in a protected local backup first.
   Do not overwrite the existing Armada service or its control/store plugins.
2. If updating Loader, install only this drop-in, after confirming the file does not already exist:

   ```sh
   test ! -e /etc/systemd/system/plugin_loader.service.d/20-preserve-armada.conf
   sudo install -d /etc/systemd/system/plugin_loader.service.d
   sudo install -m 644 postboot/proxy/20-preserve-armada.conf /etc/systemd/system/plugin_loader.service.d/20-preserve-armada.conf
   sudo systemctl daemon-reload
   ```

   Stop if the `test` fails. Review the existing drop-in instead of overwriting it.
3. Import the subscription through DeckyClash locally. Retain a nonempty controller secret.
   Keep remote controller access off. Protect private config files with mode 0600 and their directories with mode 0700.
   The examples contain `REPLACE_*` values. Do not install them as complete settings or commit edited copies.
4. Read the existing core status in DeckyClash. Stop the core through its UI before editing.
   Stop Loader to avoid a concurrent settings rewrite:

   ```sh
   sudo systemctl stop plugin_loader.service
   ```

## Apply the allowlisted edits

Use a fresh backup directory. It must not exist and must be outside the checkout.
The backup contains the original private config and override; keep it private.

```sh
sudo python3 postboot/proxy/deckyclash-local.py configure \
  --homebrew "$HOME/homebrew" \
  --backup-dir "$HOME/.local/state/caihong-proxy-rollback"
```

The script uses DeckyClash's bundled `ruamel.yaml` on the device.
It merges only the compatibility template and changes these settings:
`autostart=false`, `skip_steam_download=false`, `allow_remote_access=false`,
`override_dns=true`, `enhanced_mode=fake-ip`, and `log_level=INFO`.
It does not change subscription IDs, URLs, node definitions, the controller secret, or account data.
It never prints settings or private parser errors.
If an edit fails after backup creation, keep Loader stopped and use the restore command below.

```sh
sudo systemctl start plugin_loader.service
```

DeckyClash validates imported subscriptions and generates `running_config.yaml` when starting the core.
Before that start, validate a private full candidate containing your subscription and the merged switches:

```sh
sudo "$HOME/homebrew/plugins/DeckyClash/bin/mihomo" -t \
  -f REPLACE_PRIVATE_FULL_CONFIG \
  -d "$HOME/homebrew/data/DeckyClash"
```

The candidate must be a full Mihomo config, not the partial YAML template in this directory.
Keep its controller on authenticated loopback and retain your reviewed local route exclusions.
Run the core test locally and resolve its errors before changing routes.
The candidate and generated `running_config.yaml` contain private data. Do not print or commit them.

## Select HK and validate routing

Create a private selection file from the template, then replace only the node placeholder locally:

```sh
install -d -m 700 "$HOME/.config/caihong-proxy"
install -m 600 postboot/proxy/hk-selection.example.json "$HOME/.config/caihong-proxy/hk-selection.json"
```

Start the core in DeckyClash, then read safe status and select the exact HK node:

```sh
sudo python3 postboot/proxy/hk-controller.py status \
  --settings "$HOME/homebrew/settings/DeckyClash/config.json"
sudo python3 postboot/proxy/hk-controller.py select-hk \
  --settings "$HOME/homebrew/settings/DeckyClash/config.json" \
  --selection "$HOME/.config/caihong-proxy/hk-selection.json"
```

The helper ignores ambient proxy variables and refuses HTTP redirects.
It connects only to `127.0.0.1` using the private port and Bearer secret.
Output contains routing booleans and selection-match state, not node names or subscription metadata.
The exact node name is operator-selected; the helper does not infer geolocation from its name.

Check these results locally before enabling autostart:

- Safe status shows global mode, TUN enabled, auto-route true, auto-redirect false, and LAN access false.
- A public HTTPS request without an explicit proxy exits in HK.
- Steam store/community and a real Steam download use the selected node in the local dashboard.
- A UDP game or STUN check succeeds through the selected node.
- System DNS queries use the intended fake-IP/TUN path.
- IPv6 has no unintended direct public path. Keep strict routing enabled.
- Existing local device access remains available through reviewed route exclusions.

No public endpoint, raw connection dump, or private route table is saved by these helpers.

## Test stop, restart, then autostart

1. Stop the core in DeckyClash.
2. Confirm its TUN interface and policy routes are removed and ordinary network access returns.
3. Start the core again. Rerun `select-hk` and check Steam access and the selected route.
4. Stop Loader, enable autostart using the original rollback set, and restart Loader:

   ```sh
   sudo systemctl stop plugin_loader.service
   sudo python3 postboot/proxy/deckyclash-local.py enable-autostart \
     --homebrew "$HOME/homebrew" \
     --backup-dir "$HOME/.local/state/caihong-proxy-rollback"
   sudo systemctl start plugin_loader.service
   ```

5. Confirm the core returns, HK selection persists, and Steam access works.
   Keep the original service-enable state unless intentionally changing boot behavior.
   A normal later reboot can verify boot persistence after the stop/restart checks pass.

The recorded assessment passed clean stop and restart with these compatibility switches.
This preservation does not add an independent root Mihomo service, process-name killer, firewall rule,
router setting, or second proxy daemon.

## Rollback

Stop the core in DeckyClash first, then stop Loader:

```sh
sudo systemctl stop plugin_loader.service
sudo python3 postboot/proxy/deckyclash-local.py restore \
  --homebrew "$HOME/homebrew" \
  --backup-dir "$HOME/.local/state/caihong-proxy-rollback"
sudo systemctl start plugin_loader.service
```

The restore action copies back only the original two private files.
Original autostart behavior also returns. Inspect that state before restarting if a proxy must remain off.
Confirm the TUN interface and policy routes are gone when the core is stopped, and normal DNS/network access returns.
Do not run broad `iptables`/`nft` flushes or reset unrelated network services.

Remove the service drop-in only if this procedure created it:

```sh
sudo rm -- /etc/systemd/system/plugin_loader.service.d/20-preserve-armada.conf
sudo systemctl daemon-reload
```

If Loader or the plugin was upgraded, use the separate protected upstream-install backup to restore that version.
The local config backup covers only the two edited files; it does not replace a full private installation backup.
See `../docs/desktop-proxy.md` for the native menu, pen, controller, HK Steam download-region,
and historical validation details.
