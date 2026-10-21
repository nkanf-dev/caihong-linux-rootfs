# Steam Dual-mode VRChat Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user start VRChat VR or desktop mode from Steam without manual shell startup, while preserving the verified private Proton/FEX route.

**Architecture:** Use Steam's real launch-choice arguments to select desktop or VR in a single app-scoped orchestration wrapper. Desktop forwards the normal protected launch with explicit desktop mode and never starts or stops SteamVR. VR reuses a healthy SteamVR/ALVR runtime, or starts it once from a clean closed state; a bounded readiness gate precedes the unchanged game launch. Route only the game's audio namespace when the headset devices exist. Unsafe/crashed/ambiguous prerequisites stop with actionable diagnostics; no restart loop, account action, or global FEX/network changes.

**Tech Stack:** Python standard library, Steam launch options and URI invocation, existing portable runtime wrappers/retry gate, ALVR API/events, PipeWire/Pulse routing helpers.

---

### Task 1: Establish Steam mode selection and protected command contract
- [x] Inspect cached or public official app info for app 438100 launch entries and exact desktop/VR arguments.
- [x] Preserve exact original executable/EAC command chain and existing private launcher.
- [x] Test VR, desktop, ambiguous arguments, and unchanged command forwarding with fixtures.

### Task 2: Implement one-start orchestration
- [x] Write fake-runtime tests before implementation for already-ready reuse, clean cold start, missing headset, process collision, stale marker/ALVR safe mode, startup failure, and timeout.
- [x] Automatically prepare a one-use receipt only for a clean normal closed state; do not automatically erase evidence or unblock an unexplained crash.
- [x] Start SteamVR once, verify same-run ALVR loading and runtime/headset readiness with bounded waits, then execute the unchanged VRChat protected command.
- [x] Desktop mode must not touch SteamVR, ALVR, audio routes, or VR-specific environment.

### Task 3: Prepare installation, rollback, and audio integration
- [x] Provide local dry-run installation and rollback records with user paths expanded at install time.
- [ ] Add optional bounded audio routing after ALVR nodes and the game's namespace appear, using dynamic identities and transaction rollback.
- [x] Document off-head headset sleep, cold-boot IPC directory creation, native overlay limits, and pending charged-device acceptance.

### Task 4: Validate, preserve, and publish
- [x] Run mocked unit and integration tests without device access while the headset charges.
- [x] Review secret/identifier/large-artifact audit and explicitly admit new source files.
- [x] Root commits and pushes reviewed source only to the user's existing feature branch.
- [ ] After charging, test Steam desktop, clean cold VR start, close/reopen VR, already-running reuse, headset absent, and audio/mic/overlay. Do not label one-click startup fully verified before these live checks.
