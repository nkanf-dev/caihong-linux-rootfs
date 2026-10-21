#!/usr/bin/env python3
"""SteamVR app250820 entry: admit a clean normal start, then original runtime wrapper."""
import importlib.util
import os
from pathlib import Path
import sys
import time
from clean_gate import private_lock, prepare_clean, write_private
from dual_mode import LaunchError
from runtime_backend import Runtime

def load_outer():
    here=Path(__file__).resolve().parent
    location=here/"runtime/steamvr_runtime_escape.py"
    if not location.is_file(): location=here.parent/"pcvr/runtime/steamvr_runtime_escape.py"
    if not location.is_file(): raise LaunchError("The preserved SteamVR runtime bundle is missing")
    sys.path.insert(0,str(location.parent))
    spec=importlib.util.spec_from_file_location("caihong_original_steamvr_runtime",location)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run(args,env):
    outer=load_outer()
    # Validate before any receipt write. The actual wrapper performs this again at exec.
    outer.prepare(args,dict(env))
    runtime=Runtime(env)
    # The descriptor closes at exec. Holding it until outer consumes prevents competing
    # app250820 entries from consuming the same receipt. No process is stopped.
    with private_lock(runtime.runtime_state,"receipt.lock"):
        if runtime.admission_live(ignore_pid=os.getpid()):
            raise LaunchError("A SteamVR startup is already in progress; no second receipt or runtime was started")
        prepare_clean(runtime.settings,runtime.runtime_state,runtime.state,check_closed=runtime._closed)
        # Only this live PID generation is a startup hint, never a previous run's time.
        ticks=int(Path("/proc/self/stat").read_text().rsplit(")",1)[1].split()[19])
        write_private(runtime.state/"steamvr-start.json",{"created_at":time.time(),"pid":os.getpid(),"start_ticks":ticks})
        original=sys.argv
        try:
            sys.argv=[str(Path(outer.__file__))]+list(args) if getattr(outer,"__file__",None) else ["steamvr_auto"]+list(args)
            return outer.main()
        finally:
            sys.argv=original

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if args[:1]==["--"]: args=args[1:]
    try:
        if os.getuid()==0 or not sys.platform.startswith("linux"):
            raise LaunchError("Run from the non-root Linux Steam desktop session")
        run(args,dict(os.environ))
    except (LaunchError,OSError,ValueError,RuntimeError):
        error=sys.exc_info()[1]
        message=str(error) if isinstance(error,LaunchError) else "SteamVR prerequisite failed; review the private launcher status and runtime settings"
        print("SteamVR launch: "+message,file=sys.stderr)
        return 1
    return 0

if __name__=="__main__": sys.exit(main())
