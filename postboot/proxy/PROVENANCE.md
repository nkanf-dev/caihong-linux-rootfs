# Provenance and scope

The source-origin paths below are relative to the local assessment root.
They identify the selected input files; they are not links to private local storage.
No raw input log, private subscription store, credentials, account file, device address, or binary is included.

## Custom material

The pen bridge, pure tests, and user unit are custom assessment code, copied unchanged.
Their runtime has no third-party Python dependency.
The other delivered scripts, examples, partial override, and docs are new custom preservation material.
They retain the narrow API behavior and compatibility switches described by the inputs.
No DeckyClash, Decky Loader, Mihomo, or Steam implementation code is vendored.
The native menu helper calls the documented observed setting API; it is not a copied Steam bundle.

| Relative assessment input | SHA256 of input | Use |
| --- | --- | --- |
| `pen-steamui-bridge/implementation/pen_steamui_bridge.py` | `d941fa30286ceb85192108e8aa545cde03efae4e1c0cc794969513e8bc44a2e5` | `desktop/pen_steamui_bridge.py` |
| `pen-steamui-bridge/implementation/test_pen_steamui_bridge.py` | `6a4cb8c451ddfe4a9050092bdc08dad50857f2e1b110bf04bd279dd36f67d1f4` | `desktop/test_pen_steamui_bridge.py` |
| `pen-steamui-bridge/deploy/pen-steamui-bridge.service` | `0257c9ebe121d97b1ebffb244ff38d3389bfba1c2ebc50ede1e9dd81f9378b8b` | `desktop/pen-steamui-bridge.service` |
| `installation/CONTINUATION.json` | `5f08eeb54b5fd625ffd891df7f80ecbf4697941135c4fb15daeef14d6c6624d7` | `historical state summary only` |
| `installation/kde-menu-status.json` | `83c19e0b556925fb3aa369c4cb27272dca3a48ada5ea7a7e4d1e3d594cdc2093` | `native menu state summary only` |
| `installation/peripheral-status.json` | `ce29dbcc7ffff46522a129061cfa32448627fc8efadfba397c0beb647b0ca7e6` | `controller state summary only; pen item superseded by continuation` |
| `proxy-install/verification-summary.json` | `f16530121f4314d423f2159921d075d9593168b0afb9100750f0ff57d18e731f` | `historical proxy state summary only` |
| `proxy-install/fix_tun_routing.py` | `b57c49a3bf66d8792cb7a3295bd70d00667b5cc4874bf0035f9256be8f58394b` | `compatibility switches reimplemented; not copied` |
| `proxy-install/activate_deckyclash.py` | `114da9bb9f35dc58e3aba1decba3e32b64d83009f4a481dec7096c6467ebdfc9` | `autostart switches reimplemented; not copied` |
| `proxy-install/controller_ops.py` | `e0404eea0b17114515a7b1a687699894d2b891be612fc408ef550d2d83ad3b05` | `loopback API action reimplemented; not copied` |
| `host-source/steamui-switch-desktop-evidence.md` | `6bc8113611a83adf2ade2902da664802417ef7fdc9d4e184be942443c349d13f` | `native settings API behavior; no source excerpt copied` |

## Third-party release references

Obtain these components from upstream, keep their license notices with their own installation,
and verify native ARM64 assets before replacing an installed component.
The recorded release metadata identifies these assets; no download was performed for this preservation.

- Decky Loader: <https://github.com/SteamDeckHomebrew/decky-loader/releases/tag/v3.3.0>, `PluginLoader-arm64`.
  Recorded SHA256: `8ef5dcf36cbbbb6e97201a6baed5d79c4cc44ec27789fc9af1c5b6ae8f0b25b6`.
- DeckyClash: <https://github.com/chenx-dust/DeckyClash/releases/tag/v1.3.5>, `DeckyClash-full-linux-arm64.zip`.
  Recorded SHA256: `e839ec206fcc31126ed9a7e2e8c9aad6930ad313985a826c783edc05ce56f139`.
  The inspected upstream source carries BSD-3-Clause notices for Chenx Dust and Steam Deck Homebrew.
- Mihomo: <https://github.com/MetaCubeX/mihomo>. The recorded installed core reported 1.19.31.
  Obtain its license and bundled notices from its upstream package.

The service drop-in changes only Loader environment variables. It does not replace the Armada unit.
The YAML file contains only custom configuration values and has no subscription or proxy definition.
