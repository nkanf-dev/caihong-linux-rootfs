# Caihong post-boot recovery

This directory preserves the repairs and app-scoped PCVR chain used on 2026-10-21.
It contains source, patches, safe configuration templates, local tests, and rollback steps.
The scripts use the user's home directory or explicit arguments. They do not depend on the assessment workspace.

## Start here

1. Read [current validation](docs/current-validation.md).
2. Restore [desktop, pen, controller, and proxy](docs/desktop-proxy.md).
3. Restore [desktop VRChat](vrchat/README.md) before attempting VRChat VR.
4. Restore the [Android switch UI source](android-switch/README.md) when needed; no boot action is part of this archive.
5. Read the [SteamVR/ALVR recovery guide](pcvr/README.md).
6. Run the local checks in [validation](docs/validation.md).

The full path is native ARM64 Steam → Valve runtime → stock app FEX → full x86_64 SteamVR 2.17.10 → ALVR 20.14.1 → PICO 4 Ultra.
The private VRChat FEX route is separate. Do not substitute its FEX globally or into the SteamVR route.

## Storage boundary

Keep private backups, prefixes, Steam data, ALVR client identities, proxy subscriptions, and build outputs out of Git.
The current local-only backup location is `.local-artifacts/backups/` inside this checkout, excluded through `.git/info/exclude`; it is not included in a clone or push.
Use private directories with mode 0700 and files with mode 0600. Original boot, AVB, GPT, partition, prefix and runtime backups were moved to the Mac after file-size and SHA256 verification; duplicate runtime backup directories were then removed from the device.
No cleanup command in this directory deletes those backups.

Hardware, kernel, image creation, and partition installation remain covered by the repository's existing [English README](../README.md), [Chinese README](../README.zh-CN.md), `scripts/`, and `rootfs/` sources.
This subtree does not change partition or boot layouts and contains no flash image.

## Source and license scope

[PROVENANCE.md](PROVENANCE.md) records the preserved custom repairs and third-party source locations.
ALVR patch/build sources keep their upstream license files. Custom preservation scripts are offered under [MIT](LICENSE).
Do not infer a license change for the repository's kernel files or other upstream components.
