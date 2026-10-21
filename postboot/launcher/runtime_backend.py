"""Linux backend for the bounded app-scoped launcher; no global configuration writes."""
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from dual_mode import LaunchError, Snapshot, steam_environment
from clean_gate import directory, private_lock, prepare_clean, read_private, valid_receipt, reviewed_receipt, write_private

ROLES=("vrserver","vrcompositor","vrmonitor","vrstartup","vrwebhelper","vrdashboard")
@dataclass(frozen=True)
class Process:
    pid: int
    role: str
    ticks: int
    started: float
    ppid: int = 0
    fex: bool = False

def process_role(comm,args):
    names=[comm]
    if args:
        first=Path(args[0]).name
        names.append(first)
        if first in ("FEX","FEXInterpreter") and len(args)>1:
            names.append(Path(args[1]).name)
    for role in ROLES:
        if any(n==role or n.startswith(role+".") for n in names): return role
    return None

def processes(proc=Path("/proc")):
    if not proc.is_dir(): raise LaunchError("Linux procfs is required")
    boot=float(next(l.split()[1] for l in (proc/"stat").read_text().splitlines() if l.startswith("btime ")))
    hz=os.sysconf("SC_CLK_TCK")
    uptime=float((proc/"uptime").read_text().split()[0])
    result=[]
    game=False
    for path in proc.iterdir():
        if not path.name.isdecimal() or int(path.name)==os.getpid(): continue
        try:
            if path.stat().st_uid != os.getuid(): continue
            argv=[a.decode(errors="replace") for a in (path/"cmdline").read_bytes().split(b"\0") if a]
            comm=(path/"comm").read_text().strip()
            if comm.lower() in ("vrchat.exe","launch.exe") or (argv and Path(argv[0]).name.lower()=="vrchat.exe"):
                game=True
            role=process_role(comm,argv)
            if role:
                fields=(path/"stat").read_text().rsplit(")",1)[1].split()
                ticks=int(fields[19])
                result.append(Process(int(path.name),role,ticks,boot+ticks/hz,int(fields[1]),
                                      bool(argv and Path(argv[0]).name in ("FEX","FEXInterpreter"))))
        except (OSError,ValueError,IndexError): continue
    # A short-lived FEX fork clone can keep its parent's argv before exec.
    # Count only independent roots for singleton roles, not that same-role child.
    identities={(p.pid,p.role) for p in result}
    result=[p for p in result if not ((p.ppid,p.role) in identities and p.fex and 0<=uptime-p.ticks/hz<=2)]
    return sorted(result,key=lambda p:p.pid),game

STAMP=re.compile(r"^([A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9]{1,2} [0-9]{4} [0-9:.]+) ")
HEADER=re.compile(r"\bstartup with PID\s*=\s*(\d+)",re.I)

def log_proof(texts,live):
    """Require each marker after an exact PID startup header in the same log segment."""
    expected={p.pid:p for p in live if p.role in ("vrserver","vrmonitor")}
    loaded=ready=False
    for text in texts:
        context=None
        for line in text.splitlines():
            match=STAMP.match(line)
            if not match: continue
            try: stamp=datetime.strptime(match[1],"%a %b %d %Y %H:%M:%S.%f").timestamp()
            except ValueError: continue
            header=HEADER.search(line)
            if header:
                p=expected.get(int(header[1]))
                context=p if p and stamp>=p.started-2 else None
            if context is None or stamp < context.started: continue
            if context.role=="vrserver" and "Loaded server driver alvr_server (IServerTrackedDeviceProvider_004) from " in line:
                loaded=True
            if context.role=="vrmonitor" and "[System] Transition from " in line and "to 'SteamVRSystemState_Ready'" in line:
                ready=True
    return loaded,ready

class Runtime:
    def __init__(self,env,*,home=None,proc=Path("/proc")):
        self.env=dict(env)
        self.home=Path.home() if home is None else home
        self.steam=self.home/".local/share/Steam"
        self.state=self.home/".local/state/caihong-vrchat-launcher"
        self.runtime_state=self.home/".local/state/caihong-pcvr"
        self.settings=self.steam/"config/steamvr.vrsettings"
        self.proc=proc
        self.events=None
        self.receipt=None
        self.request=None
        self.lock=None
        self.log_files={}
    def __enter__(self):
        self.lock=private_lock(self.state,"launch.lock")
        self.lock.__enter__()
        return self
    def __exit__(self,*exc):
        if self.events is not None: self.events.close()
        if self.lock is not None: self.lock.__exit__(*exc)
    def monotonic(self): return time.monotonic()
    def record(self,event,**fields):
        write_private(self.state/"status.json",{"event":event,"time":time.time(),**fields})
    def _closed(self):
        live,game=processes(self.proc)
        if live or game: raise LaunchError("Close SteamVR and VRChat normally before a clean cold start")
    def _starting(self):
        receipt=self.runtime_state/"retry-receipt.json"
        launch=self.runtime_state/"runtime-launch.json"
        now=time.time()
        if receipt.exists():
            data=read_private(receipt)
            if valid_receipt(data,now):
                if self.request_admitted(data):
                    status=self.state/"status.json"
                    if status.exists() and read_private(status).get("event")=="failed":
                        raise LaunchError("This receipt already requested SteamVR and failed; obtain a new reviewed receipt")
                    return True
                return not reviewed_receipt(data)
            raise LaunchError("An invalid pending SteamVR receipt needs review")
        return self.admission_live()
    def request_admitted(self,receipt):
        path=self.state/"steam-request.json"
        if not path.exists(): return False
        data=read_private(path)
        return data.get("appid")==250820 and data.get("receipt_created_at")==receipt.get("created_at")
    def claim_request(self,receipt):
        if self.request_admitted(receipt):
            raise LaunchError("This receipt already requested SteamVR; no second request is allowed")
        write_private(self.state/"steam-request.json",{"appid":250820,"receipt_created_at":receipt["created_at"],
                                                     "created_at":time.time(),"attempts":1})
    def admission_live(self,ignore_pid=None):
        now=time.time()
        admission=self.state/"steamvr-start.json"
        if admission.exists():
            data=read_private(admission)
            if data.get("pid")==ignore_pid: return False
            if not 0<=now-data.get("created_at",0)<=90: return False
            try:
                ticks=int((self.proc/str(data["pid"])/"stat").read_text().rsplit(")",1)[1].split()[19])
                return ticks==data.get("start_ticks")
            except (OSError,KeyError,ValueError,IndexError): return False
        return False
    def inspect(self):
        live,game=processes(self.proc)
        counts={r:sum(p.role==r for p in live) for r in ROLES}
        marker=self.settings.with_name("vrserver_crash_timestamp.txt")
        data=json.loads(self.settings.read_text())
        blocked=data.get("driver_alvr_server",{}).get("blocked_by_safe_mode") is not False
        session=self.home/".config/alvr/session.json"
        if session.is_symlink() or not session.is_file(): raise LaunchError("The existing private ALVR session is required")
        # Read only trust booleans. Do not retain, record, or print client identities.
        clients=json.loads(session.read_text()).get("client_connections",{})
        trusted=any(c.get("trusted") is True for c in clients.values())
        texts=[]
        for name in ("FEX.txt","FEX.previous.txt"):
            path=self.steam/"logs"/name
            try:
                # Fixed maximum; do not read a growing log without a bound.
                with path.open("rb") as stream:
                    stream.seek(0,2)
                    end=stream.tell()
                    stream.seek(0)
                    head=stream.read(512*1024)
                    if end>512*1024:
                        stream.seek(max(512*1024,end-2*1024*1024))
                        tail=stream.read(2*1024*1024)
                    else: tail=b""
                    texts.append((head+b"\n"+tail).decode(errors="replace"))
            except FileNotFoundError: pass
        loaded,ready=log_proof(texts,live)
        server=next((p for p in live if p.role=="vrserver"),None)
        mapped=False
        if server:
            try:
                mapped="/driver_alvr_server.so" in (self.proc/str(server.pid)/"maps").read_text()
            except OSError: pass
        consumed=False
        path=self.runtime_state/"retry-receipt-consumed.json"
        if self.receipt is not None and path.exists():
            consumed=read_private(path).get("created_at")==self.receipt.get("created_at")
        return Snapshot(processes=tuple((p.pid,p.role,p.ticks) for p in live),
                        crash_marker=marker.exists() or marker.is_symlink(),alvr_blocked=blocked,
                        trusted_client=trusted,collision=game or any(counts[r]>1 for r in ("vrserver","vrcompositor","vrmonitor")),
                        driver_loaded=loaded and mapped,monitor_ready=ready,
                        fresh_stream=bool(self.events and self.events.fresh_stream),
                        receipt_consumed=consumed,starting=not live and self._starting())
    def prepare(self):
        try:
            with private_lock(self.runtime_state,"receipt.lock"):
                # Steam may have entered its own auto wrapper since our first snapshot.
                live,game=processes(self.proc)
                if live: return False
                pending=self.runtime_state/"retry-receipt.json"
                if pending.exists():
                    self.receipt=read_private(pending)
                    if not valid_receipt(self.receipt,time.time()): raise LaunchError("Invalid pending receipt")
                    # A reviewed gate only prepares; unlike a normal launcher admission
                    # it has not requested Steam and needs this one URI.
                    if self.request_admitted(self.receipt):
                        raise LaunchError("This receipt already requested SteamVR; no second request is allowed")
                    if reviewed_receipt(self.receipt):
                        self.claim_request(self.receipt)
                        return True
                    return False
                if self._starting(): return False
                self.receipt=prepare_clean(self.settings,self.runtime_state,self.state,check_closed=self._closed)
                self.claim_request(self.receipt)
                return True
        except LaunchError as error:
            # A receipt lock contention is another startup, never permission to launch twice.
            if str(error)=="A launch or receipt transaction is already in progress": return False
            raise
    def start(self):
        self.request=subprocess.Popen(["/usr/bin/steam","steam://run/250820"],env=steam_environment(self.env),
                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       close_fds=True,start_new_session=True)
    def wait(self,seconds):
        if self.request is not None and self.request.poll() not in (None,0):
            raise LaunchError("Native Steam rejected the SteamVR start request; no retry was issued")
        from alvr_events import Events, ProtocolError
        start=time.monotonic()
        if self.events is None:
            client=Events()
            try: client.open(timeout=min(0.25,seconds))
            except OSError:
                client.close()
                remaining=seconds-(time.monotonic()-start)
                if remaining>0: select.select([],[],[],remaining)
                return
            except ProtocolError:
                client.close()
                raise LaunchError("ALVR API protocol or version does not match pinned 20.14.1") from None
            self.events=client
        try: self.events.wait(max(0,seconds-(time.monotonic()-start)))
        except (OSError,ProtocolError):
            self.events.close()
            self.events=None
            raise LaunchError("The current ALVR event connection ended; inspect the runtime before another attempt") from None
