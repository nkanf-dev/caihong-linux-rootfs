# Small synthetic regressions

These programs exercise emulated Linux syscall, signal, ptrace, and memory behavior. They do not load a game, EAC, or account data.

Preserved from `StonkGuy/FEX` tag `eac-2610.3`:

| Directory | Historical purpose/result |
| --- | --- |
| `signal-mask` | Guest signal-mask fidelity; expected PASS was observed, as was the native ARM64 reference. |
| `seccomp-trap` | Synthetic seccomp signal semantics; expected PASS was observed with the test-table option. |
| `execve-seccomp` | One unresolved timeout with `FEX_NEEDSSECCOMP=1`. |
| `smc-same-page` | One unresolved default-mode failure. |
| `ptrace-sigbus` | One unresolved real-SIGBUS recovery failure. |

Exact source blob hashes and preserved SHA-256 values are in `../evidence/source-provenance.json`. The MIT license is in `FEX-LICENSE`.

Compile on a machine with Clang's x86-64 target. Write outputs outside this source tree. For example, on the target device:

```sh
mkdir -p "$HOME/.local/share/caihong-vrchat-regression-bin"
sh signal-mask/build.sh clang "$HOME/.local/share/caihong-vrchat-regression-bin/signal_mask_test"
```

Each build script has the adjacent `tools/static-link.py` fallback. The static x86-64 executables use raw syscalls and do not need a guest C library. They are Linux programs; do not execute them on macOS. Use the isolated validator for actual target execution.

These five sources are a compact preservation set. `build/validate_fex.py compile-tests` obtains the full 33-case table from the pinned FEX checkout; `build/evidence/eac-tests/run-all.sh` preserves that table for host inspection.
