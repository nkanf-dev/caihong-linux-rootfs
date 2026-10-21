# Return to Android power menu implementation plan

**Goal:** Add `返回 Android` to the existing Steam GamepadUI power menu.

**Architecture:** A small Decky plugin uses the official Decky module/React patch helpers and a guarded in-memory hook for the observed Steam power dialog. It never edits a Steam bundle. A root Decky backend reuses the existing Linux-side `caihong-slot android` command, verifies the approved Android A / Linux B deployment, and requests a normal reboot only after explicit confirmation.

**Scope:** Host source, build, mock tests, install/rollback recipe. No device connection, install, slot write, service restart, or reboot in this task. Change only this subtree.

## Steps

- [x] Inspect cached SteamUI power dialog, existing slot script, and official Decky APIs.
- [x] Add fail-closed backend with read-only preparation, expiring single-use confirmation, trusted deployment config and command digests, slot/bootability checks, reboot inhibitors, and readback.
- [x] Add guarded native power-dialog hook, distinct confirmation, safe cancel, and unload cleanup.
- [x] Pin public build dependencies, add provenance, and produce a small installable plugin with reversible host-tested installer.
- [x] Run Python mock tests, frontend lifecycle/confirmation tests, and production build.
- [x] Record host validation and exact later Linux installation / visual cancel / CLI checks.

## Acceptance

No startup/poll/cancel path writes a slot. Unknown slot/config/API/privilege/reboot condition stops. Ordinary reboot only; no force flags, game termination, global sudo/polkit change, PIN change, Steam bundle patch, or live action. Original Steam actions remain intact. Independent parent audit is required before commit/push.
