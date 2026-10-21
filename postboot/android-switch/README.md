# Android boot switch source

This directory preserves the Android-side Armada dual-boot UI. The app checks an Android-a / Linux-b deployment, selects slot b through the AIDL Boot HAL, verifies the selection, and reboots after user confirmation. The existing Linux-to-Android launcher is [`caihong-switch-to-android.desktop`](../../rootfs/archlinuxarm/usr/share/applications/caihong-switch-to-android.desktop), backed by `caihong-slot`. The `../desktop` component handles menu, pen, and controller integration.

## Contents

- `src/`: UI, root helper, Binder client, switch policy, deadlines, and process cleanup.
- `aidl/v1/`: frozen AOSP boot-control v1 interface and interface hash.
- `res/` and `AndroidManifest.xml`: launcher, theme, and app metadata.
- `tests/`: Python configuration tests and host Java tests with fake backends.
- `diagnostic/`: optional diagnostic-specific source and tests. Shared Java comes from `src/`.
- `build.py`: offline SDK recipe with explicit toolchain, configuration, output, and optional signing inputs.
- `config/deployment.example.json`: disabled device/image configuration.
- `provenance/`: source-origin checksums, historical build metadata, and archive checksums.
- `THIRD_PARTY_NOTICES.md`: AOSP origin and license details.

The archive contains source and metadata only. Binary outputs, signing keys, passwords, device PINs, screenshots, device dumps, and kernel images are excluded.

## Host-only source tests

Use Python 3.9 or newer and a JDK. JDK 17 is the documented Android build toolchain. Source tests need no SDK, signing key, device, network, or root access.

From this directory:

```sh
python3 -B build.py --test
```

Use `--java-home` or `ARMADA_JAVA_HOME` to select a JDK. The recipe also accepts `JAVA_HOME`, then falls back to `java` and `javac` on `PATH`.

The tests compile into a temporary directory inside this component and remove it on completion. The process-session test starts only a short-lived local Java test child. The tests never call the Android helper or device tools.

The Java tests cover:

- Device, root, slot, snapshot, partition, deployment, and image policy.
- Pre-write checks, active-slot readback, reboot order, and failure handling through fake backends.
- Image-prefix hashing, block identity, deadlines, stdin cancellation, bounded process output, and cleanup.
- Binder exception handling, response shape, transaction IDs, interface version/hash, and Parcel recycling through test doubles.
- Optional diagnostic selection and post-write reads through a fake backend.

## Offline build setup

Install JDK 17, Android SDK platform `android-35`, and build-tools `35.0.0` before building. The recipe never downloads dependencies.

Set `ANDROID_SDK_ROOT` to the installed SDK, or pass `--sdk-root`. Set `JAVA_HOME` or pass `--java-home` to select the JDK. Tool paths are not tied to a host account or a package manager.

For a disabled source build:

```sh
python3 -B build.py --output-dir "$HOME/.cache/android-switch-build"
```

This produces an aligned, unsigned APK and the app-process helper JAR. The unsigned APK must be signed before installation. The build also checks the frozen AIDL transaction map using the installed SDK AIDL compiler.

Optional targets:

```sh
python3 -B build.py --helper-only --output-dir "$HOME/.cache/android-switch-helper"
python3 -B build.py --diagnostic-only --output-dir "$HOME/.cache/android-switch-diagnostic"
```

Generated configuration and compiler intermediates stay in temporary build directories. Builds do not rewrite the checked-in `TargetConfig.java`. The chosen output directory holds binaries and `SHA256SUMS`; keep those outputs outside version control.

## Device configuration

The checked-in example has `deploymentReady=false`, placeholder model/device values, zero image length, and an empty image digest. It keeps the original fixed mapping: Android slot a, Linux slot b, exactly 64 GiB GPT `linux`, `/dev/block/by-name/linux`, and `/dev/block/by-name/boot_b`.

For a later authorized deployment:

1. Copy `config/deployment.example.json` to `config/deployment.local.json`, or to a private path outside this source tree.
2. Fill the verified model and device code. Do not use a serial number, account, address, or PIN.
3. Set the exact deployed boot-image length and lowercase SHA256. Set its upstream workflow run and source commit for traceability.
4. Verify the independent Linux partition, canonical boot_b identity, slot mapping, bootable Android fallback, and snapshot state.
5. Set `deploymentReady=true` only after that deployment is verified. Build with `--config` pointing to the reviewed configuration.

The schema accepts only the documented fields. Device PINs and credentials have no configuration field. Keep private deployment config outside the committed archive.

The app does not create partitions, flash images, download images, alter `misc`, or use a PATH-provided `bootctl`. Its root helper verifies Binder identity and the device/partition/image policy before changing the next slot. The switch path checks a 60-second confirmation deadline, reads the selected slot back, verifies target bootability, and then requests reboot. The helper has a separate 120-second limit. Managed stdin and bounded process cleanup stop delayed authorization requests.

## Signing and installation handoff

The recipe defaults to an unsigned APK. For an update, use the existing trusted signing identity managed outside this source tree. Pass `--keystore`, `--key-alias`, and optionally `--ks-pass-env`. The password comes from the named environment variable; the default name is `ANDROID_SWITCH_KEYSTORE_PASSWORD`. Load it through your secret manager. The script reads the key and does not create or modify it.

Example using an already provisioned external key and environment variable:

```sh
python3 -B build.py --config config/deployment.local.json \
  --output-dir "$HOME/.cache/android-switch-release" \
  --keystore "$HOME/.local/share/android-switch-signing/release.p12" \
  --key-alias release
```

The package is `cn.armada.dualswitch`, version `0.1.0`, versionCode `1`. The manifest declares no permissions, service, or receiver. The launcher Activity is the sole exported component and does not accept automatic-switch intent parameters. KernelSU supplies root authorization.

Installation and boot-state changes are separate authorized device tasks. First preserve the installed APK and signing-certificate digest in private operator storage. Confirm a working Android-a fallback and a recovery method before replacing the app. Install the reviewed, signed package with that device's approved local workflow. Start with the app's **Check device** action, review its blockers, and grant root only to the trusted package. The actual switch needs a separate confirmation in the UI.

## Optional diagnostic source

`BootControlDiagnostic` supports `status` and `select-b-no-reboot`. The latter writes the next slot once after the same deployment policy and fresh HAL checks pass. It records before/after state and whether the `void` Binder call returned normally. It never launches another process or requests a reboot. Treat selection as a boot-state write even though it does not reboot.

The diagnostic shares `TargetConfig`, `Policy`, `BlockIdentity`, `ImageDigest`, `SwitchDeadline`, and `BootControlClient` with the app. Its source and tests are preserved for inspection and later authorized use. This archive task did not run either command on a device.

## Rollback

These are preparation steps, not commands executed by the archive task.

- To abandon a source change, restore the source files from version control and rerun `python3 -B build.py --test`.
- To abandon a new build, remove its chosen output directory. Leave the external signing key intact.
- To restore the UI, use a previously preserved trusted APK with a compatible package/signing identity through the approved Android install workflow. Keep newer source and build outputs separate for review.
- Replacing or uninstalling the app leaves the selected boot slot unchanged. Inspect current and next slots before any reboot. Use the existing reviewed recovery/switch procedure to select Android a when necessary.
- If a selection may have reached the HAL before an error or timeout, reread next-slot state before taking another action. The helper stops reboot on failed verification and does not automatically write slot a back.
- Do not edit boot partitions, GPT, or kernel files as part of a UI rollback.

## Provenance and checksums

`provenance/source-origin.json` records source-relative origin paths and SHA256 values. `provenance/historical-build.json` records historical snapshot metadata, including the exact upstream image identifiers and artifact hashes. Historical build records describe a frozen enabled candidate; the archive uses the disabled example config. Current device/deployment status belongs in the repository's current status record.

`provenance/ARCHIVE_SHA256SUMS` covers every delivered file except itself. Verify it with a SHA256 checker from this directory. Source test results and the preservation checks are summarized in `provenance/source-validation.json`.
