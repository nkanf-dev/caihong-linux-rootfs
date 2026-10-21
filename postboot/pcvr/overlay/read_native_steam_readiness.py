#!/usr/bin/env python3
"""Read the current Steam readiness property. Never dispatch a URI.

Run only after the user resumes testing. This file has no device scheduling.

ABI: ValveSoftware/openvr commit 0924064316de3effbcd1acf1e309182a2deb1c05,
headers/openvr_capi.h: IVRPaths_002, VR_IVRPaths_FnTable, PathRead_t.
https://github.com/ValveSoftware/openvr/blob/0924064316de3effbcd1acf1e309182a2deb1c05/headers/openvr_capi.h

Root container 0x600000000: offline-proven in the exact native client constructor
and ReadPathBatch callers. See the source and binary-proof references in README.md.
The corrected root has NOT yet passed a device read. A host mock is not that test.

Requires an existing vrserver. Initializes one native Background client and closes
only that client. No StartVR, QuitAllVR, URI dispatch, or path-property writes.
"""
import ctypes
import json
import os
from pathlib import Path
import stat
import sys

ABI_SOURCE_COMMIT = "0924064316de3effbcd1acf1e309182a2deb1c05"
INTERFACE = b"FnTable:IVRPaths_002"
PROPERTY = b"/steam/vr_connection_ready"
ROOT_CONTAINER = 0x600000000
STRING_TAG = 5
MAX_BYTES = 4096

class PathRead(ctypes.Structure):
    _fields_ = [
        ("ulPath", ctypes.c_uint64),
        ("pvBuffer", ctypes.c_void_p),
        ("unBufferSize", ctypes.c_uint32),
        ("unTag", ctypes.c_uint32),
        ("unRequiredBufferSize", ctypes.c_uint32),
        ("eError", ctypes.c_int32),
        ("pszPath", ctypes.c_char_p),
    ]
assert ctypes.sizeof(PathRead) == 40
assert [getattr(PathRead, name).offset for name in (
    "ulPath", "pvBuffer", "unBufferSize", "unTag", "unRequiredBufferSize",
    "eError", "pszPath")
] == [0, 8, 16, 20, 24, 28, 32]

READ_BATCH = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_uint64,
                             ctypes.POINTER(PathRead), ctypes.c_uint32)
TO_HANDLE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(ctypes.c_uint64),
                            ctypes.c_char_p)

def read_property(lib):
    """Return public status plus a private value. Never print the value."""
    error = ctypes.c_int32(-1)
    table = lib.VR_GetGenericInterface(INTERFACE, ctypes.byref(error))
    status = {"interface": INTERFACE.decode(), "interface_error": error.value}
    if not table or error.value != 0:
        return status, None
    slots = ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p))
    if not slots[0] or not slots[2]:
        return {**status, "failure": "missing_read_function"}, None
    read = READ_BATCH(slots[0])
    to_handle = TO_HANDLE(slots[2])
    handle = ctypes.c_uint64(0)
    handle_error = to_handle(ctypes.byref(handle), PROPERTY)
    status["handle_error"] = handle_error
    if handle_error != 0 or handle.value == 0:
        return status, None
    buffer = ctypes.create_string_buffer(MAX_BYTES)
    batch = PathRead(handle.value, ctypes.cast(buffer, ctypes.c_void_p),
                     len(buffer), 0, 0, -1, None)
    result = read(ROOT_CONTAINER, ctypes.byref(batch), 1)
    status.update(batch_error=result, property_error=batch.eError,
                  tag=batch.unTag, required_size=batch.unRequiredBufferSize)
    if result != 0 or batch.eError != 0 or batch.unTag != STRING_TAG:
        return status, None
    if not 2 <= batch.unRequiredBufferSize <= len(buffer):
        return {**status, "failure": "invalid_or_empty_length"}, None
    raw = buffer.raw[:batch.unRequiredBufferSize]
    if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        return {**status, "failure": "invalid_string_termination"}, None
    try:
        value = raw[:-1].decode("utf-8", "strict")
    except UnicodeError:
        return {**status, "failure": "invalid_utf8"}, None
    return status, value

def write_private_value(path, value):
    """Create one 0600 file in an existing private caller-owned directory."""
    path = Path(path)
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise ValueError("absolute output file path required")
    parent = path.parent
    parent_stat = parent.lstat()
    if parent.is_symlink() or not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.getuid():
        raise ValueError("output parent must be a caller-owned directory")
    if stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise ValueError("output parent must be private (mode 0700 or stricter)")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value.encode("utf-8"))
    except BaseException:
        path.unlink(missing_ok=True)
        raise

def existing_server_pids():
    result = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text().strip() == "vrserver":
                result.append(int(proc.name))
        except OSError:
            pass
    return result

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit("usage: read_native_steam_readiness.py /absolute/libopenvr_api.so /private/token-file")
    library, token_path = map(Path, argv)
    if not library.is_absolute() or not token_path.is_absolute():
        raise SystemExit("absolute paths required")
    if token_path.exists() or token_path.is_symlink():
        raise SystemExit("refusing to overwrite output token file")
    servers = existing_server_pids()
    if not servers:
        raise SystemExit("no existing vrserver; refusing background initialization")
    lib = ctypes.CDLL(str(library), mode=os.RTLD_NOW | os.RTLD_LOCAL)
    lib.VR_InitInternal2.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.c_int32, ctypes.c_char_p]
    lib.VR_InitInternal2.restype = ctypes.c_uint32
    lib.VR_ShutdownInternal.argtypes = []
    lib.VR_ShutdownInternal.restype = None
    lib.VR_GetGenericInterface.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32)]
    lib.VR_GetGenericInterface.restype = ctypes.c_void_p
    error = ctypes.c_int32(-1)
    initialized = False
    status = {"scope": "one property read; no URI dispatch", "existing_servers": servers}
    try:
        token = lib.VR_InitInternal2(ctypes.byref(error), 3, None)
        status.update(init_error=error.value, token_nonzero=bool(token))
        if error.value != 0 or not token:
            print(json.dumps(status))
            return 1
        initialized = True
        read_status, value = read_property(lib)
        status.update(read_status)
        if value is None:
            print(json.dumps(status))
            return 1
        write_private_value(token_path, value)
        status.update(value_saved=True, value_length=len(value), output_mode="0600")
        print(json.dumps(status))
        return 0
    finally:
        if initialized:
            lib.VR_ShutdownInternal()

if __name__ == "__main__":
    raise SystemExit(main())
