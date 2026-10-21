# Launcher implementation contract

Owned source: this directory only. Existing `vrchat/` and `pcvr/` files are
read-only dependencies, copied intact by the installer.

## Mode and executable contract

`auto` selects desktop only from one exact original `--no-vr` token. The recorded
Windows Steam VR entry has no arguments. Unsupported VR overrides and duplicate
or malformed desktop flags fail before runtime construction. Explicit desktop
mode adds one `--no-vr` only if absent. The command must contain exactly one stock
FEX wrapper and one original `launch.exe`; the private prefix, executable private
tool, ownership, and experimental-option guards run before VR startup.

The original command is forwarded once to the preserved private route. Only that
existing route substitutes the private FEX wrapper. No direct VRChat.exe or EAC
binary mutation is allowed.

## One-start state machine

- Closed, clean, explicitly ALVR-unblocked: lock receipt, issue one receipt,
  request native Steam app 250820 once, wait for proof and consumed receipt.
- Starting (including Steam's automatic VR dependency start): wait boundedly;
  never send a second URI.
- Healthy existing runtime: collect fresh events and reuse without receipt/start.
- Live incomplete runtime: wait boundedly, never stop or restart it.
- Crash marker, blocked/unknown ALVR state, independent duplicate singleton,
  game collision, PID generation change, missing trusted client, invalid receipt,
  endpoint/protocol failure, or deadline: stop with fixed local diagnostics.

App250820 uses `steamvr_auto.py`: validate the original wrapper command, lock,
prepare only a clean receipt or retain a valid pending receipt, then delegate the
existing outer wrapper which checks closure and consumes the receipt once.
The lock descriptor closes at exec. App438100 uses a separate launch lock.
Locks never authorize clearing markers or safe mode. The existing reviewed gate
alone owns backup/unblock recovery.

## Evidence

Runtime proof binds generic FEX startup PID headers to real live process role and
Linux start ticks/wall time. It searches the bounded head and tail of both FEX log
rotations. Readiness requires same-run loaded driver + monitor Ready + driver map,
then two kinds of freshly received ALVR event samples. ALVR reads only loopback
8082 and checks pinned version 20.14.1. Session trust is read locally without
retaining identifiers. Status stores fixed events, times, booleans, and fixed
recovery guidance, not commands, environments, sessions, or client identities.

## Scope and validation

No device calls or runtime mutation during host tests. No new game shortcuts,
Steam VDF writes, login/trust/world actions, audio routes, service, restart loop,
or persistent background helper. The installer prints two launch templates and
uses digest-guarded rollback. Device acceptance and four remaining audio/mic/
right-eye/overlay items are owned by the charged-device test phase.
