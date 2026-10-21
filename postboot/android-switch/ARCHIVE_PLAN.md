# Android Switch Source Archive Implementation Plan

**Goal:** Preserve the Android-side boot switch UI and selected diagnostic source as a portable, source-only component.

**Architecture:** Keep the deployed snapshot's app Java, frozen AIDL, XML resources, manifest, and host tests. Keep only diagnostic-specific Java and its test under a separate source tree. Replace deployment-specific configuration with a disabled example, and make SDK, JDK, build output, and optional signing inputs explicit.

**Tech stack:** Python standard library, JDK 17, Android SDK platform 35 and build-tools 35.0.0.

## Tasks

- [x] Inventory the source snapshot and verify source checksums against its historical source manifest.
- [x] Copy the allowlisted app Java, AIDL, XML, manifest, and tests. Exclude binary outputs, keys, device logs, screenshots, and deployment config.
- [x] Preserve diagnostic-specific Java and its coordinator test without duplicating shared source.
- [x] Write a portable offline build recipe and disabled example device configuration. Add host-only test mode with temporary class output.
- [x] Add source-origin and archive checksum manifests with relative origin names. Record sanitized historical artifact and upstream image metadata.
- [x] Write setup and rollback instructions without running device operations.
- [x] Run Python syntax/config tests, Java fake-backend tests, XML parsing, checksum verification, and source/secret boundary checks.

No commit. No device commands, network access, boot-state writes, kernel changes, APK builds, or signing operations in this task.
