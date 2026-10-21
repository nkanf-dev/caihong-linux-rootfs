# Host validation — 2026-10-21

## Passed

- `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`: **32/32** mock/filesystem tests.
- `npm run typecheck`: pass.
- `npm test`: **16/16** frontend hook/session/React component tests.
- `npm run build`: pass; generated `dist/index.js` is about 14 KB.
- Exact upstream refs recorded in `source-references.json` and `frontend-references.json`.

The Python tests replace all boot-control, busctl, systemctl, process-group, and subprocess calls with mocks. Installer tests use temporary filesystem fixtures and a fixture-only uid override. No test calls the real slot launcher, qbootctl, busctl, systemctl, or a device.

Coverage includes: zero-action module load/unload; no writes on prepare/cancel/expired or wrong token; duplicate confirm; unload during prepare; fixed deployment and tool digests; wrong current/active slot; A bootability/success; typed malformed bus JSON; shutdown inhibitors/plan/reboot overrides; option capability preflight; wrong loopback/privilege; script failure/readback mismatch; phase-specific selected-A reboot failure; output caps on stdout and stderr; invalid UTF-8/process start error; whole-process-group failure cleanup; installer refusal of wrong version/digest/unapproved deployment; unchanged other plugins; modified config/plugin preservation; symlink and writable namespace refusal; pinned-parent write isolation.

Frontend tests exercise the actual confirmation view with injected native component handles: Cancel focus, no RPC on render, no confirm on Cancel, one explicit confirm, rapid repeated click rejection, busy cancel rejection, unmount cancellation, and bounded phase-aware error text. Hook tests cover scope, unrelated menus, shape mismatch, decorated forwarder detection, and cleanup.

## Later Linux checks

Follow `README.md` after the charging-only period. Required checks are actual Loader version/loopback, installed tool digests, approved image/deployment identity, live boot-control current/active B and A bootable/successful, exact target busctl JSON, native controller power-menu open/cancel, hook unload/reload, and a separately chosen Android boot test.

This host pass records source and mock behavior. It does not claim a visible target menu item, successful target install, or completed Android boot. No ADB/device command, device install, slot write, service/Steam restart, or reboot ran in this implementation task.
