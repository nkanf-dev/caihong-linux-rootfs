# Testing and historical result

## Historical device result

The preserved run used the private `eac-2610.3` FEX copy with the stock x86-64 rootfs. `evidence/synthetic-results.json` retains the outcome fields for all 35 runs, with machine-local log paths omitted.

**32 of 35 results matched expectations. The full suite did not pass.**

| Unresolved case | Recorded result |
| --- | --- |
| `execve-seccomp.FEX_NEEDSSECCOMP_1` | Timed out; exit 124; no final RESULT. |
| `smc-same-page` | RESULT: FAIL; exit 6. |
| `ptrace-sigbus` | RESULT: FAIL; exit 1; real-SIGBUS recovery difference. |

Two additional cases were intentional negative controls and behaved as expected:

- `smc-hot-page.FEX_SMCHOTPAGEFAULTS_0`: expected FAIL and a nonzero exit.
- `pop-fault`: expected FAIL and a nonzero exit; its fix was withdrawn in this tag.

The stock-rootfs `true` smoke, native ARM64 signal-mask reference, and focused ptrace-inject/signal-mask/signal-regs/debug-register/regset checks matched expectations. The private per-app scope preserves the desktop experiment without changing global FEX for other games.

The desktop Steam → original launch.exe → EAC → VRChat chain then reached EAC 301 and the login screen at the historical timestamp in `evidence/SUCCESS.json`. It was later closed normally for SteamVR work. No account login or world join was performed. A subsequent authorized attempt removed only `--no-vr`; VR and audio validation were pending at this preservation checkpoint.

## Host preservation checks

Run from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_launcher build/test_recipe.py test_preservation
```

Result: **24 tests passed**.

- 13 launcher checks use mocked `execv` or owner-directory fixtures. They check single exact wrapper substitution, preserved argument order, unchanged stock wrapper, no prefix-content edits, app/prefix guards, rejected experimental options, UID/runtime selection, socket length, private modes, and safe route records.
- Five recipe checks cover the 33-row pinned table, ELF architecture, PASS/negative-control exit semantics, short sockets, and portable/private-server cleanup settings.
- Six preservation checks cover source checksums, source/submodule lock agreement, all 35 historical results, historical status and VR-attempt boundaries, Python/JSON parsing, and source-only file hygiene.

Temporary host fixtures stay below this directory and are removed after each test. No target connection, live launcher exec, game process, EAC process, prefix installation, or global tool update occurs in these tests.

Five small synthetic programs and their build scripts are preserved under `regressions/`. Their pinned source/blob hashes are checked on the host. Actual Linux execution remains a target-side validation step; no regression executable is archived here.
