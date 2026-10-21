# Compositor main-task name repair

This optional negotiation-shim constructor repairs the exact compositor main task name. It requires the reviewed ELF build ID and a main-task comm of `vrcompositor.re` or `vrcompositor`. It uses `prctl` on the main thread. If the layer first loads on a worker, it writes the same process group's main-task comm instead of renaming RenderThread.

- `compositor_main_comm.h`: exact reviewed source.
- `ALVR_Negotiate.cpp.in` and `ALVR_Negotiate.before.cpp.in`: portable shim templates with `@SESSION_PATH@`.
- `main-comm-shim.patch`: sanitized template patch. `manifest.json` records both preserved and original input SHA256 values.
- `tests/`: exact logic/constructor tests and test-only ELF/process stubs. Generated binaries stay external.

Run from the repository root:

```sh
python3 postboot/pcvr/patches/main-comm/tests/run_tests.py
python3 postboot/pcvr/patches/main-comm/tests/run_tests.py --sanitizers
```

The portable layer build accepts `--main-comm` to include this repair. It substitutes the explicit `--session-path` into the template and copies the exact header into the external build directory.

Host logic and mocked-constructor tests pass in release and ASan/UBSan modes. These checks use the source files above. The root reports a successful target GCC16 rebuild. In the same runtime run, the driver loaded at 17:09:17.991, `ALVR_COMPOSITOR_COMM status=set` appeared at 17:09:19, and `VR_Init successful` appeared at 17:09:20.779. These are root-owned runtime observations. A game acceptance test remains separate.
