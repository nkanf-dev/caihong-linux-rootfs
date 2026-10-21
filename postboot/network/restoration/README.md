# Restore the original Armada package payloads

This directory preserves the reviewed RPM specs and public provenance for three
local restoration packages. It contains no source archives, ELF files, RPMs,
private backups, credentials, or raw device receipts.

| Package | Original Armada version | Local restoration version |
|---|---|---|
| steamos-manager | 26.4.1-1.fc44.armada.aarch64 | 26.4.1-3.fc44.caihong.aarch64 |
| gamescope-session | 0~20260920git.0232e0c-1.100109.fc44.armada.noarch | 0~20260920git.0232e0c-3.fc44.caihong.noarch |
| inputplumber | 0.81.0-1.fc44.armada.aarch64 | 0.81.0-3.fc44.caihong.aarch64 |

These are locally rebuilt RPMs with unmodified official package payloads. They
are not original signed Armada RPMs. The original software version is retained.
The two older session/input versions require a deliberate package downgrade from
the generic Terra versions.

## Evidence preserved here

Each `PROVENANCE-*.json` records the original RPM identity, source-image identity,
verified OCI layer digest, exact archive allowlist, file hashes/modes, symlink
targets, original package flags, and the reviewed spec digest. The manager
provenance also records the original RPMDB chunk and matching daemon/CLI hashes.
The specs come from the immutable input snapshots used for the native builds.

The confirmed manager source patch is
`packages/steamos-manager/patches/0012-wifi-Always-write-wpa_supplicant-as-the-backend.patch`
at the recorded stable image revision. Later Armada source revisions call the
same patch `0011`; use the recorded revision when checking this recovery.

The live manager validation sent `SetWifiBackend(u0)` after installing the restored
package. The call returned successfully, kept `wpa_supplicant`, and left the
NetworkManager process and activation time unchanged. Session and physical input
checks remain separate from package-file verification.

## Recover source inputs from the exact official image

Use an operator-selected private work directory. Do not download build artifacts
into this repository or the synced human document library.

1. Read the exact manifest digest, image revision, and component layer digest
   from the selected provenance file. Resolve the manifest by its digest, not
   the mutable `stable` tag.
2. Fetch the referenced compressed OCI layer from
   `https://ghcr.io/v2/armada-os/armada/blobs/<layer-digest>` using the normal OCI
   registry authentication flow. Check the downloaded SHA-256 before opening it.
3. For `steamos-manager`, use the complete 44-member reviewed package layout.
   For the two merged chunks, select only the original RPM ownership allowlist
   and ancestor directories listed in `archive_members`. Never extract all files
   from a merged chunk.
4. Reject absolute paths, `..` path components, duplicate members, unsafe member
   types, unexpected owners/modes, and symlinks whose normalized target is not an
   allowed regular file. Match every regular file's SHA-256 and size. The original
   RPMDB SHA-256 was also checked when these inputs were prepared.
5. Create the source archive named by `source_archive` under the private work
   directory. Preserve the reviewed relative paths, ownership, modes, and link
   targets. Recreating a gzip/tar archive can change its compressed digest even
   when file bytes match. The replay verifier deliberately requires the exact
   reviewed source archive as well as all payload file hashes; do not update a
   digest merely to bypass a mismatch. Review any reconstructed archive as a new
   input before a new build.

The public source revision and package build specs are available in the
[Armada repository](https://github.com/armada-os/armada). Use the pinned image
revision recorded in the JSON files.

## Verify preserved inputs and build natively

For the manager inputs:

```sh
python3 verify_repack_inputs_manager.py --source-dir /private/build-inputs
mkdir -p /private/build-inputs/rpmbuild/BUILD /private/build-inputs/rpmbuild/BUILDROOT \
  /private/build-inputs/rpmbuild/RPMS /private/build-inputs/rpmbuild/SOURCES \
  /private/build-inputs/rpmbuild/SPECS /private/build-inputs/rpmbuild/SRPMS
cp /private/build-inputs/steamos-manager-armada-26.4.1.tar.gz \
  /private/build-inputs/rpmbuild/SOURCES/
cp manager.spec /private/build-inputs/rpmbuild/SPECS/
rpmbuild -bb --define '_topdir /private/build-inputs/rpmbuild' \
  /private/build-inputs/rpmbuild/SPECS/manager.spec
```

Use `verify_repack_inputs_gamescope_session.py` or
`verify_repack_inputs_inputplumber.py` with the matching spec and source archive
for the other packages. All builds run on native Fedora AArch64. They copy
prebuilt payloads; they do not compile Rust. Automatic native ELF/shell
requirements remain enabled. Stripping, debug rewriting, and build-id link
regeneration are disabled so the official binary hashes remain intact.

Before installation, inspect `rpm -qp --requires`, `rpm -qplv`, and
`rpm -qp --scripts`. Extract the built RPM in the private audit directory and
compare every owned file and link with the provenance. Check native library
resolution and preview the transaction. Only the intended local packages should
change. No service scriptlets are added by these specs.

## Root-owned live gates

- Save the current package files and local configuration privately.
- Keep the desktop available and Steam/game mode stopped during session-package
  replacement. Preserve `/etc` and user drop-ins.
- Record original persistent/runtime mask states. For the manager, runtime-mask
  and stop the user service before the system service. Old Terra postun scripts
  can request restarts; the temporary masks also block D-Bus autostart.
- Restore only masks introduced by this operation. Reload unit metadata and start
  system manager, then user manager once when their original state permits it.
- For InputPlumber, keep a second input/control route. Record composite devices,
  target devices and active state before one controlled service stop/start.
  Preserve local device/profile mappings. Do not trigger all udev devices or
  reboot automatically.
- Verify package hashes/modes, SELinux labels, D-Bus interfaces, Wi-Fi backend,
  hotspot discovery, saved connection, game-session startup and physical input.
- Use the [exact package hold tool](../locks/README.md) for the approved 39 names.
  Inspect the installed DNF5 help before choosing a per-transaction override for
  an approved local restoration. Leave the persistent hold in place for normal
  upgrades.

Do not undo the full user update or replace unrelated packages. The six Mesa
runtime packages have a separate dependency/graphics review and are not included
in these three specs.
