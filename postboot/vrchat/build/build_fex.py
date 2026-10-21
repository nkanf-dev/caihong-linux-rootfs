#!/usr/bin/env python3
"""Build only, using an already prepared rootless Fedora 44 ARM64 compiler image."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

GIB=1024**3
DEFAULT_WORK=Path.home()/".local/share/caihong-vrchat-fex-build"

def output(args,env):
    return subprocess.check_output(args,env=env,text=True).strip()

def measure(work,env):
    usage=shutil.disk_usage(work)
    sizes={}
    for name in ["FEX","build-steam","stage","logs","eac-tests"]:
        path=work/name
        if path.exists():
            sizes[name]=int(output(["du","-sx","--block-size=1",str(path)],env).split()[0])
    return {"unix":time.time(),"free_bytes":usage.free,"total_bytes":usage.total,"sizes_bytes":sizes}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work",type=Path,default=DEFAULT_WORK)
    p.add_argument("--image",default="localhost/caihong-vrchat-fex-builder:fc44")
    args=p.parse_args()
    if os.uname().sysname!="Linux" or os.uname().machine!="aarch64" or os.sysconf("SC_PAGE_SIZE")!=4096:
        p.error("Run on the target Fedora aarch64 Linux device with 4 KiB pages")
    if os.getuid()==0:
        p.error("Use the owner's non-root account; do not use sudo")
    work=args.work.expanduser().resolve()
    work.mkdir(parents=True,exist_ok=True)
    (work/"logs").mkdir(exist_ok=True)
    (work/"container-home").mkdir(exist_ok=True)
    env=dict(os.environ,TMPDIR="/tmp",XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
             DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{os.getuid()}/bus")
    rootless=output(["podman","info","--format","{{.Host.Security.Rootless}}"],env)
    if rootless!="true":
        p.error("Podman must be rootless")
    image=json.loads(output(["podman","image","inspect",args.image],env))[0]
    if image["Architecture"]!="arm64" or image["Os"]!="linux":
        p.error("Prepared image must be native linux/arm64")
    # Run by immutable local ID; no pull, DNF, image update, or host RPM operation occurs here.
    image_id=image["Id"]
    lock=work/"logs/builder-image-lock.json"
    if lock.exists() and json.loads(lock.read_text())["Id"]!=image_id:
        p.error("Builder image changed; review and archive the old lock before selecting a new compiler image")
    lock.write_text(json.dumps({k:image.get(k) for k in ["Id","Digest","RepoDigests","Architecture","Os","Created"]},indent=2)+"\n")
    initial=measure(work,env)
    if initial["free_bytes"]<20*GIB:
        p.error("At least 20 GiB must remain free on the work filesystem")
    recipe=Path(__file__).resolve().with_name("container_build.py")
    if not recipe.is_file():
        p.error("Keep container_build.py beside this script")
    statefile=work/"logs/build-state.json"
    logfile=work/"logs/build-container.txt"
    budgetfile=work/"logs/storage-budget.jsonl"
    name="caihong-fex-build-"+str(os.getpid())
    command=["podman","run","--rm","--name",name,"--pull=never","--platform=linux/arm64",
             "--userns=keep-id","--user",f"{os.getuid()}:{os.getgid()}","--network=host",
             "--read-only","--cap-drop=all","--security-opt=no-new-privileges",
             "--memory=4g","--memory-swap=6g","--pids-limit=512",
             "--tmpfs=/tmp:rw,nosuid,nodev,size=512m","--workdir=/work",
             "-v",f"{work}:/work:rw,Z","-v",f"{recipe}:/recipe/container_build.py:ro,Z",
             "--env=HOME=/work/container-home","--env=TMPDIR=/tmp",image_id,
             "python3","/recipe/container_build.py"]
    state={"state":"running","container":name,"image_id":image_id,"jobs":2,
           "memory_bytes":4*GIB,"memory_swap_total_bytes":6*GIB,"started_unix":time.time(),
           "scope":"build and stage only; no deployment"}
    statefile.write_text(json.dumps(state,indent=2)+"\n")
    stop=threading.Event()
    budget_breach=threading.Event()
    def monitor():
        with budgetfile.open("a",buffering=1) as log:
            while not stop.is_set():
                snapshot=measure(work,env)
                log.write(json.dumps(snapshot)+"\n")
                if snapshot["free_bytes"]<20*GIB:
                    budget_breach.set()
                    subprocess.run(["podman","stop","--time=10",name],env=env,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    return
                stop.wait(30)
    with logfile.open("a",buffering=1) as log:
        proc=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
        watcher=threading.Thread(target=monitor,daemon=True)
        watcher.start()
        try:
            rc=proc.wait()
        except KeyboardInterrupt:
            subprocess.run(["podman","stop","--time=10",name],env=env,check=False)
            rc=130
        finally:
            stop.set()
            watcher.join(timeout=15)
    state.update(state="budget-stop" if budget_breach.is_set() else ("build-staged" if rc==0 else "failed"),
                 exit_code=rc,finished_unix=time.time(),storage=measure(work,env))
    statefile.write_text(json.dumps(state,indent=2)+"\n")
    print(f"{state['state']}: {logfile}")
    if rc==0:
        print(f"Stage: {work}/stage. Run separate validation before any deployment.")
    return 1 if budget_breach.is_set() else rc

if __name__=="__main__":
    sys.exit(main())
