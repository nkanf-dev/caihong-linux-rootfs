# ALVR v20.14.1 PR3357 source backport

This package preserves the exact six-file present-wait backport and its original verification script.

- `base/`: six official unmodified source files, without a nested Git repository.
- `alvr-v20.14.1-pr3357.patch`: minimal six-file backport.
- `upstream-pr3357.patch`: exact upstream patch mail, including its public author metadata.
- `manifest.json`: pinned stable commit, base and fixed Git blobs, and SHA256 digests.
- `verify_apply.py`: original check/apply helper, preserved byte-for-byte.

Check a writable external copy of the official stable source tree:

```sh
python3 postboot/pcvr/patches/present-wait/verify_apply.py "$ALVR_SOURCE"
python3 postboot/pcvr/patches/present-wait/verify_apply.py "$ALVR_SOURCE" --apply
```

The helper verifies all six stable base blobs before applying anything. It verifies all six fixed upstream blobs after `--apply`. The `base/` subset is enough for patch checks. The small C++ layer build closure is in `../../build/source/`.

The fix adds owner-aware `vkWaitForPresentKHR` and queued present IDs. It keeps the older present-ID/present-wait extension family and filters unsupported newer swapchain extension families. Its ID waits finish at queue time, as in the upstream fix.

Run `python3 -m unittest discover -s postboot/pcvr/tests/pose -p 'test_*.py'` from the checkout for base/apply/reverse and digest checks. Source licenses are in `../../licenses/ALVR-vulkan-layer-MIT.txt`. Full source provenance is in `manifest.json` and `../../build/source-manifest.json`.
