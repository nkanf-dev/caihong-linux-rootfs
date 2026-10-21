# ALVR namespace audio routing helper implementation plan

**Goal:** Route only a reviewed VRChat Steam audio namespace to the current ALVR sink and microphone, with a private transaction journal and guarded rollback.

**Architecture:** Read native pactl JSON through an injectable adapter. Resolve the exact app PID, namespace devices, external loopback streams, and ALVR endpoints with vrserver ownership checks. Apply two checked moves only after saving rollback identities; compensate on failure. Do not create endpoints or change defaults.

**Tech stack:** Python 3 standard library, native pactl, unittest with a fake pactl adapter.

## Files

- `route_namespace.py`: JSON discovery, identity guards, journal, route/rollback transaction, CLI.
- `test_route_namespace.py`: mocked pactl snapshots and success/failure/rollback cases.
- `README.md`: native-user invocation, stream lifecycle, scope and recovery.

## Steps

- [x] Write tests for exact discovery, dynamic IDs, missing/ambiguous endpoints, owner/group mismatch, dry-run, successful transaction, exclusive private journal, second-move failure compensation, stale rollback and successful rollback.
- [x] Run `python3 -m unittest discover -s pcvr/audio -v` from postboot and confirm the new tests fail before implementation.
- [x] Implement strict discovery and two-move transaction with persisted started/result/readback events.
- [x] Run the tests and a synthetic copy of the supplied JSON snapshot. No live pactl process is called by tests.
- [x] Write README and the source diagnosis report. Inspect the final diff. Do not commit or deploy.
