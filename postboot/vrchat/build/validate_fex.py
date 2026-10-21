#!/usr/bin/env python3
"""Inspect, compile regressions, or explicitly validate a staged FEX. Never deploy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import tempfile
import time

PIN = "938eedfcd79eb00e86561fbdf4933770766f0ba9"
IMAGE = "localhost/caihong-vrchat-fex-builder:fc44"
REQUIRED = ["FEX", "FEXBash", "FEXGetConfig", "FEXOfflineCompiler", "FEXServer",
            "FEXServerManager", "FEXpidof"]
MINIMUM = ["ptrace-inject", "signal-mask", "ptrace-dregs", "ptrace-regsets", "ptrace-sigbus", "signal-regs"]

def capture(args, *, cwd=None, env=None, timeout=120):
    return subprocess.run(list(map(str, args)), cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)

def checked(args, **kwargs):
    r = capture(args, **kwargs)
    if r.returncode:
        raise RuntimeError(f"Command failed ({r.returncode}): {' '.join(map(str,args))}\n{r.stdout}")
    return r.stdout

def elf(path, machine):
    with path.open("rb") as f:
        b = f.read(64)
    if len(b) < 64 or b[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", b, 18)[0] != machine:
        raise RuntimeError(f"Wrong ELF architecture or format: {path}; expected e_machine={machine}")

def pin(src):
    for ref in ["HEAD", "eac-2610.3^{commit}"]:
        got = checked(["git", "-C", src, "rev-parse", ref]).strip()
        if got != PIN:
            raise RuntimeError(f"Pin mismatch: {ref}={got}")

def cases(src):
    text = (src / "eac-tests/run-all.sh").read_text()
    block = text.split("TESTS='",1)[1].split("'",1)[0]
    rows = [line.split() for line in block.splitlines() if line.strip()]
    if not rows or any(len(r) != 4 for r in rows):
        raise RuntimeError("Unexpected pinned test table format")
    return rows

def container_compile(work):
    src = work / "FEX"
    pin(src)
    out = work / "eac-tests/bin"
    out.mkdir(parents=True,exist_ok=True)
    logs = work / "logs/test-build"
    logs.mkdir(parents=True,exist_ok=True)
    names = {}
    for name, binary, expected, envopt in cases(src):
        if name in names:
            continue
        names[name] = binary
        command = ["sh", src / "eac-tests" / name / "build.sh", "clang", out / binary]
        r = capture(command, cwd=out)
        (logs / (name + ".txt")).write_text(r.stdout)
        if r.returncode:
            raise RuntimeError(f"Test compilation failed: {name}; see {logs}")
        elf(out / binary, 62)
    env = dict(os.environ, NATIVE_CC="clang")
    native = out / "signal_mask_native_aarch64"
    r = capture(["sh", src / "eac-tests/signal-mask/build.sh", "native", native], cwd=out, env=env)
    (logs / "signal-mask-native.txt").write_text(r.stdout)
    if r.returncode:
        raise RuntimeError("Native aarch64 signal-mask reference failed to compile")
    elf(native,183)
    report = {name:{"binary":binary,"sha256":hashlib.sha256((out/binary).read_bytes()).hexdigest()}
              for name,binary in names.items()}
    (logs / "test-manifest.json").write_text(json.dumps(report,indent=2)+"\n")
    print(f"Compiled {len(names)} pinned x86-64 regressions plus the native aarch64 signal-mask reference")

def inspect(work):
    stage = work / "stage"
    if not stage.is_dir():
        raise RuntimeError(f"Missing stage directory: {stage}")
    log = work / "logs/native-inspect"
    log.mkdir(parents=True,exist_ok=True)
    loader = Path("/lib/ld-linux-aarch64.so.1")
    if not loader.exists():
        raise RuntimeError("Native aarch64 ELF loader not found")
    report = {}
    files = [stage / "usr/bin" / name for name in REQUIRED] + [stage / "FEXCompatTool"]
    for path in files:
        elf(path,183)
        # The host loader checks the actual host library versions and dependency paths.
        r = capture([loader,"--list",path],env={"PATH":"/usr/bin:/bin","LC_ALL":"C"})
        (log / (path.name+".loader.txt")).write_text(r.stdout)
        if r.returncode or "not found" in r.stdout:
            raise RuntimeError(f"Host runtime dependency mismatch: {path}; see {log}")
        report[str(path.relative_to(stage))] = {"bytes":path.stat().st_size,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    for name in ["VERSIONS.txt","ConfigTemplate.json","emulator.json","toolmanifest.vdf"]:
        p=stage/name
        if not p.is_file() or not p.stat().st_size:
            raise RuntimeError(f"Incomplete stage: {name}")
        report[name]={"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
    (log/"stage-manifest.json").write_text(json.dumps(report,indent=2)+"\n")
    (log/"host-rpms.txt").write_text(checked(["rpm","-q","glibc","libstdc++","libgcc"]))
    (log/"host-glibc.txt").write_text(checked(["getconf","GNU_LIBC_VERSION"]))
    print("Stage architecture and native host runtime dependency checks passed")

def one_test(args, cwd, env, logfile, expected="PASS", timeout=60):
    # A separate session lets timeout terminate test children without touching unrelated FEX processes.
    with logfile.open("w") as log:
        p = subprocess.Popen(list(map(str,args)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                             start_new_session=True)
        timed_out=False
        try:
            rc=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            rc=124
    text=logfile.read_text(errors="replace")
    results=re.findall(r"RESULT: ([A-Z]+)",text)
    got=results[-1] if results else "NO_RESULT"
    # PASS requires rc=0; expected negative controls require a nonzero exit and RESULT: FAIL.
    okay=not timed_out and got==expected and ((rc==0) if expected=="PASS" else (rc!=0))
    return {"rc":rc,"result":got,"expected":expected,"timeout":timed_out,"okay":okay,
            "log":str(logfile)}

def validate(work, rootfs, suite, inflated):
    inspect(work)
    stage=work/"stage"
    src=work/"FEX"
    binaries=work/"eac-tests/bin"
    if not rootfs.is_dir():
        raise RuntimeError("Use the existing stock x86-64 rootfs directory, not a sqsh path")
    true = rootfs / "usr/bin/true"
    if not true.is_file():
        true=rootfs/"bin/true"
    elf(true,62)
    runid=time.strftime("%Y%m%dT%H%M%S")+"-"+str(os.getpid())
    run=work/"validation"/runid
    run.mkdir(parents=True)
    # Steam builds use <data>/Server/<uid>.FEXServer.Socket, not the abstract socket override.
    # Keep this path below sockaddr_un.sun_path's 108-byte limit so FEX never uses its shared fallback.
    runtime=Path(f"/run/user/{os.getuid()}")
    if not runtime.is_dir() or runtime.stat().st_uid!=os.getuid():
        raise RuntimeError("The owner's XDG runtime directory must exist")
    private=Path(tempfile.mkdtemp(prefix="cvf-",dir=runtime))
    expected_socket=private/"data/Server"/f"{os.getuid()}.FEXServer.Socket"
    if len(os.fsencode(expected_socket))>=108:
        raise RuntimeError("Private server socket path exceeds sockaddr_un limit")
    # No Steam library or account variables are inherited. Portable mode disables the host binfmt route,
    # so guest re-exec stays on the staged FEX instead of following the installed stock interpreter.
    env={"PATH":str(stage/"usr/bin")+":/usr/bin:/bin", "HOME":str(run/"home"),
         "LANG":"C", "LC_ALL":"C", "TMPDIR":"/tmp", "XDG_RUNTIME_DIR":str(runtime),
         "FEX_ROOTFS":str(rootfs), "FEX_PORTABLE":"1",
         "FEX_SERVERSOCKETPATH":"caihong-validation-"+str(os.getpid()),
         "FEX_APP_DATA_LOCATION":str(private/"data")+"/", "FEX_APP_CONFIG_LOCATION":str(run/"config")+"/",
         "FEX_APP_CACHE_LOCATION":str(run/"cache")+"/"}
    for path in [run/"home",private/"data",run/"config",run/"cache"]:
        path.mkdir()
    (run/"config/Config.json").write_text((stage/"ConfigTemplate.json").read_text())
    if inflated:
        env.update({f"EACTEST_PAD_{i}":chr(65+i%26)*1024 for i in range(400)})
    metadata={"rootfs":str(rootfs),"rootfs_true_sha256":hashlib.sha256(true.read_bytes()).hexdigest(),
              "stage_fex_sha256":hashlib.sha256((stage/"usr/bin/FEX").read_bytes()).hexdigest(),
              "private_server_socket":str(expected_socket), "portable_mode":True,
              "inflated_environment":inflated,"scope":"synthetic regressions only; no game or EAC process"}
    (run/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
    try:
        r=capture([stage/"usr/bin/FEXGetConfig","--version"],env=env)
        (run/"version.txt").write_text(r.stdout)
        if r.returncode or "eac-2610.3" not in r.stdout:
            raise RuntimeError(f"Unexpected staged version; see {run}/version.txt")
        results={}
        # Run by the rootfs's real absolute path so no native aarch64 /usr/bin/true is selected.
        smoke=one_test([stage/"usr/bin/FEX",true],run,env,run/"smoke-true.txt",expected="NO_RESULT")
        smoke["okay"]=not smoke["timeout"] and smoke["rc"]==0
        results["stock-rootfs-true"]=smoke
        if not smoke["okay"]:
            (run/"results.json").write_text(json.dumps(results,indent=2)+"\n")
            raise RuntimeError(f"Rootfs smoke failed; see {run}")
        native=binaries/"signal_mask_native_aarch64"
        elf(native,183)
        results["native-aarch64-signal-mask"]=one_test([native],run,env,run/"native-signal-mask.txt")
        rows=cases(src)
        if not suite:
            rows=[r for r in rows if r[0] in MINIMUM]
        for index,(name,binary,expect,envopt) in enumerate(rows):
            guest=binaries/binary
            elf(guest,62)
            testenv=dict(env)
            if envopt!="-":
                key,value=envopt.split("=",1)
                testenv[key]=value
            label=name if envopt=="-" else name+"."+envopt.replace("=","_")
            result=one_test([stage/"usr/bin/FEX",guest],binaries,testenv,run/(label+".txt"),expected=expect)
            results[label]=result
            print(f"{label}: {result['result']} rc={result['rc']} expected={expect} {'PASS' if result['okay'] else 'FAILED'}",flush=True)
            (run/"results.json").write_text(json.dumps(results,indent=2)+"\n")
        okay=all(r["okay"] for r in results.values())
        print(f"Results: {run}; {'PASS' if okay else 'FAILED'}")
        if not okay:
            raise RuntimeError("Validation failed; preserve stage and logs; do not deploy")
        print("Synthetic validation complete. No deployment was performed.")
    finally:
        # The exact same short private data path selects only this run's Steam-mode server.
        # Never use pgrep, pkill, a global socket, or the installed FEXServer.
        try:
            cleanup=capture([stage/"usr/bin/FEXServer","--foreground","--kill"],env=env,timeout=10)
            (run/"private-server-cleanup.txt").write_text(cleanup.stdout+f"\nexit={cleanup.returncode}\n")
            if cleanup.returncode:
                print(f"Private server cleanup needs inspection: {private}",file=sys.stderr)
            else:
                waited=capture([stage/"usr/bin/FEXServer","--foreground","--wait"],env=env,timeout=10)
                with (run/"private-server-cleanup.txt").open("a") as log:
                    log.write(waited.stdout+f"\nwait_exit={waited.returncode}\n")
                print(f"Requested shutdown and waited on private server only: {expected_socket}",flush=True)
        except (subprocess.TimeoutExpired,OSError) as exc:
            (run/"private-server-cleanup.txt").write_text(str(exc)+"\n")
            print(f"Private server cleanup needs inspection: {private}",file=sys.stderr)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase",choices=["inspect","compile-tests","validate","suite","container-compile-tests"])
    ap.add_argument("--work",type=Path,default=Path.home()/".local/share/caihong-vrchat-fex-build")
    ap.add_argument("--image",default=IMAGE)
    ap.add_argument("--rootfs",type=Path)
    ap.add_argument("--inflated-environment",action="store_true")
    args=ap.parse_args()
    work=args.work.expanduser().resolve()
    if os.uname().sysname!="Linux" or os.uname().machine!="aarch64" or os.sysconf("SC_PAGE_SIZE")!=4096:
        ap.error("Run natively on the target aarch64 Linux device with 4 KiB pages")
    if os.getuid()==0:
        ap.error("Use the device owner's non-root account")
    if not work.is_dir():
        ap.error("The dedicated work directory must already exist")
    if args.phase=="container-compile-tests":
        container_compile(work)
    elif args.phase=="compile-tests":
        env=dict(os.environ,TMPDIR="/tmp",XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
                 DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{os.getuid()}/bus")
        command=["podman","run","--rm","--pull=never","--platform=linux/arm64","--userns=keep-id",
                 "--user",f"{os.getuid()}:{os.getgid()}","--network=none","--read-only","--cap-drop=all",
                 "--security-opt=no-new-privileges","--memory=4g","--memory-swap=6g",
                 "--pids-limit=512","--tmpfs=/tmp:rw,nosuid,nodev,size=512m",
                 "-v",f"{work}:/work:rw,Z","-v",f"{Path(__file__).resolve()}:/recipe/validate_fex.py:ro,Z",
                 "--workdir=/work","--env=HOME=/work/container-home","--env=TMPDIR=/tmp",args.image,
                 "python3","/recipe/validate_fex.py","container-compile-tests","--work=/work"]
        subprocess.run(command,env=env,check=True)
    elif args.phase=="inspect":
        inspect(work)
    else:
        if not args.rootfs:
            ap.error("--rootfs must explicitly name the existing stock x86-64 rootfs directory")
        validate(work,args.rootfs.expanduser().absolute(),args.phase=="suite",args.inflated_environment)

if __name__=="__main__":
    main()
