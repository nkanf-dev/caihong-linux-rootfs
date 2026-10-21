# Local validation and archive audit

Run these checks from the repository root with Python 3 and a C++17 host compiler.
Build and test output belongs in a separate temporary directory, not this checkout.
No command here connects to the device or changes its runtime.

```sh
python3 -m unittest discover -s postboot/tests -p 'test_*.py' -v
python3 -m unittest discover -s postboot/pcvr/tests -p 'test_*.py' -v
python3 -m unittest discover -s postboot/vrchat -p 'test_*.py' -v
python3 -m unittest discover -s postboot/vrchat/build -p 'test_*.py' -v
python3 -m unittest discover -s postboot/desktop -p 'test_*.py' -v
python3 -m unittest discover -s postboot/proxy -p 'test_*.py' -v
node postboot/desktop/test-steam-native-menu.cjs
python3 postboot/tools/check_sources.py
```

Use the component README files for pen bridge, Android UI, exact patch application, pose-unit, and compiler checks.
The ALVR unit harness replaces module discovery and unwind calls with fixtures.
The independent saved-core replay source accepts a separately retained private fixture; no core or raw stack bytes are committed.
The archive records the prior replay result and fixture digest. Keep new runtime acceptance in current validation.

## Explicit allowlist

`archive-allowlist.json` lists each admitted source with a relative destination, byte count, SHA256, and source role.
It is a content manifest, not permission to copy an entire assessment folder.
No binary, image, prefix, account/session database, subscription, credential, or bulk log is admitted.
New files need an explicit review and a new entry.

After an intentional edit to an existing allowlisted file, refresh only its existing record:

```sh
python3 postboot/tools/refresh_allowlist.py
python3 postboot/tools/audit_archive.py
```

The scanner rejects unlisted files, personal home paths, private LAN/device identifiers, account IDs, UUIDs, common credential formats, credential assignments, binary data, and files above 512 KiB.
It prints only paths and rule names, not matched values.
Local `/tmp/caihong-alvr-<uid>` socket names are runtime namespace settings; source and builds do not depend on a temporary assessment directory.

Stage only the reviewed subtree and implementation plan, then audit the actual index:

```sh
git add postboot docs/superpowers/plans/2026-10-21-postboot-pcvr-preservation.md
python3 postboot/tools/audit_archive.py --staged
git diff --cached --check
git diff --cached --stat
```

Review every staged path. Keep unrelated work and the previous main commit untouched.
The preservation delivery makes a local commit only. It does not push.

The subtree `.gitattributes` exempts only six exact upstream/reviewed payloads from whitespace diagnostics.
Their bytes and hashes are preserved, including patch context lines.
Authored files still use the normal whitespace checks.

Additional prepared-tool mock suites (no device/pactl/OpenVR initialization):

```sh
python3 -B -m unittest discover -s postboot/pcvr/audio -p 'test_*.py' -v
python3 -B -m unittest discover -s postboot/pcvr/stereo -p 'test_*.py' -v
python3 -B -m unittest discover -s postboot/pcvr/overlay -p 'test_*.py' -v
```

The reviewed counts are 31 audio, 23 stereo, and 10 overlay checks. These validate source safety and fixtures only; headset playback, microphone, visual repair, and native Steam UI remain charged-device tests.
