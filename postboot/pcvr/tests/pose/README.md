# Host pose and patch checks

Run from the repository root. Python 3 and Git are required. The C++ tests also require a C++17 compiler.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s postboot/pcvr/tests/pose -p 'test_*.py' -v
python3 postboot/pcvr/tests/pose/run_tests.py
python3 postboot/pcvr/tests/pose/run_tests.py --sanitizers
```

`run_tests.py` uses a temporary directory outside the checkout by default and removes it on exit. Use `--output-dir "$POSE_TEST_OUTPUT"` to retain outputs in an explicit external directory. Use `--compiler-command g++` to select another compiler. Sanitizer mode enables ASan and UBSan.

The C++ harness compiles the exact patched `pose.cpp`. `include/` contains test-only ELF, module, and libunwind stubs. The tests cover finite values, rotations, build IDs, bounds, ambiguity, HMD index zero, a moved stack, and unwind failures. Use real Linux headers for a layer build.

## Saved-core replay source

`replay_exact_update.cpp` retains the small replay program. The captured stack bytes and core are external. `replay-metadata.json` retains their expected byte count, SHA256, relative layout, and reviewed source digest. It omits private source paths and guest memory addresses.

```sh
python3 postboot/pcvr/tests/pose/run_tests.py --fixture "$EXTERNAL_UPDATE_FRAME"
python3 postboot/pcvr/tests/pose/run_tests.py --sanitizers --fixture "$EXTERNAL_UPDATE_FRAME"
```

The runner requires the fixture to be outside the repository. It checks its full byte count and SHA256 before compiling. The replay checks HMD zero against the captured frame and rejects the second prediction/controller records. Runtime patch diagnostics may print the recovered matrix to stderr; keep any captured output outside the repository.

These are host logic, patch integrity, and saved-memory replay tests. A runtime test checks live module discovery, libunwind behavior, transport, and headset output.
