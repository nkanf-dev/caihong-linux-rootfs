# Caihong Post-boot and PCVR Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the post-boot repairs and current PCVR chain in the user's fork under `~/clones` instead of relying on tmp.

**Architecture:** Keep reusable scripts, exact compatibility patches, sanitized templates, rollback instructions, and a current validation matrix in a dedicated post-boot subtree. Store only small necessary evidence. Exclude account material, subscription/node secrets, images, game data, large binaries, and crash dumps.

**Tech Stack:** Python, systemd user services, Decky/Mihomo configuration templates, Steam/FEX/Proton configuration, ALVR C++ Vulkan layer patches, Markdown, Git.

---

### Task 1: Move the existing fork and create a branch
- [x] Inspect Git status, remotes, and worktree metadata.
- [x] Move the existing assessment checkout to `~/clones/caihong-linux-rootfs` without deleting history or uncommitted files.
- [x] Verify branch feat/caihong-postboot-pcvr-recovery-20261021 and preserve existing unrelated files.

### Task 2: Preserve the working operating-system and proxy repairs
- [x] Review tmp evidence and copy a deliberate allowlist of desktop menu, pen/controller, Decky/Clash lifecycle, and proxy-repair scripts.
- [x] Create sanitized setup and rollback instructions; never include subscription URLs, UUIDs, keys, tokens, or account state.
- [x] Preserve volatile UFS queue mitigation as an explicitly nonpersistent diagnostic, not a proven hardware fix.

### Task 3: Preserve desktop VRChat and full SteamVR/ALVR
- [x] Document exact private FEX/Proton route and rollback without copying game/EAC binaries, account state, or prefixes.
- [x] Copy app-scoped runtime wrappers, clean safe-mode retry gate, exact HostEnv profiles, and configuration templates.
- [x] Preserve upstream present-wait patch and exact-build pose patch with tests, provenance, and runtime status clearly labeled.
- [x] Track remaining headpose, right-eye dashboard, and native Steam VR library integration separately from verified image delivery.

### Task 4: Validate and make a local preservation commit
- [x] Run source syntax checks and existing patch regression tests through their documented environments.
- [x] Audit Git staged paths and content for credentials, personal data, large artifacts, and stale tmp-only dependencies.
- [x] Commit only the preservation subtree and plan on the new branch; do not push without further user direction.
- [ ] Root appends final active-patch build/deployment results after review.
