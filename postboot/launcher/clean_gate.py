"""Private clean-start receipts. Never removes crash markers or unblocks ALVR."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import time
import uuid
from dual_mode import LaunchError

@contextmanager
def _dirfd(path,*,create=False,private=True):
    """Hold every checked directory by no-follow descriptor, including at use."""
    path=Path(path)
    if not path.is_absolute(): raise LaunchError("Launcher paths must be absolute")
    fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        current=Path(path.anchor)
        for component in path.parts[1:]:
            current=current/component
            try: child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except FileNotFoundError:
                if not create: raise
                os.mkdir(component,0o700,dir_fd=fd)
                child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.fchmod(child,0o700)
            os.close(fd)
            fd=child
            info=os.fstat(fd)
            sticky_root=bool(info.st_mode & stat.S_ISVTX) and info.st_uid==0
            if info.st_uid not in (0,os.getuid()) or (info.st_mode & 0o022 and not sticky_root):
                raise LaunchError("Launcher directory ancestors must not be writable by other users")
        info=os.fstat(fd)
        if private and (info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700):
            raise LaunchError("Launcher state must be an owner-controlled 0700 directory")
        yield fd
    except OSError:
        raise LaunchError("A launcher path is inaccessible or has an unsafe symlink ancestor") from None
    finally: os.close(fd)

def directory(path):
    with _dirfd(path,create=True): pass
    return Path(path)

def _fileinfo(info):
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077 or info.st_nlink!=1:
        raise LaunchError("Launcher state files must be private owner-controlled regular single-link files")

def _read_at(fd,name):
    source=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    with os.fdopen(source,"r") as stream:
        _fileinfo(os.fstat(stream.fileno()))
        return json.load(stream)

def read_private(path):
    path=Path(path)
    with _dirfd(path.parent) as fd: return _read_at(fd,path.name)

def write_private(path,data):
    path=Path(path)
    with _dirfd(path.parent,create=True) as fd:
        # Open the prior inode read-only for checks; never truncate it.
        try:
            previous=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except FileNotFoundError: previous=None
        if previous is not None:
            try: _fileinfo(os.fstat(previous))
            finally: os.close(previous)
        temporary=".receipt-"+uuid.uuid4().hex
        created=False
        try:
            descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            created=True
            with os.fdopen(descriptor,"w") as stream:
                os.fchmod(stream.fileno(),0o600)
                json.dump(data,stream,indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Final destination may only remain absent or a safe regular inode.
            try: info=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError: info=None
            if info is not None: _fileinfo(info)
            os.replace(temporary,path.name,src_dir_fd=fd,dst_dir_fd=fd)
            created=False
            os.fsync(fd)
        except OSError:
            raise LaunchError("Private launcher evidence could not be written safely") from None
        finally:
            if created: os.unlink(temporary,dir_fd=fd)

@contextmanager
def private_lock(state,name):
    with _dirfd(state,create=True) as parent:
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
        try:
            _fileinfo(os.fstat(fd))
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise LaunchError("A launch or receipt transaction is already in progress") from None
            yield
        finally: os.close(fd)

def reviewed_receipt(receipt):
    review=receipt.get("fault_review")
    if review is None: return False
    if not isinstance(review,str) or not review or not Path(review).is_absolute():
        raise LaunchError("A reviewed receipt requires its original absolute evidence-file path")
    path=Path(review)
    with _dirfd(path.parent,private=False) as parent:
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o022 or info.st_nlink!=1 or info.st_size==0:
                raise LaunchError("The reviewed evidence must be a nonempty owner-controlled regular file")
        finally: os.close(fd)
    return True

def valid_receipt(receipt,now):
    if not isinstance(receipt,dict): return False
    stamp=receipt.get("created_at")
    shape=(type(receipt.get("appid")) is int and receipt["appid"]==250820 and
           type(receipt.get("attempts")) is int and receipt["attempts"]==1 and
           type(stamp) in (int,float) and math.isfinite(stamp) and
           0 <= now-stamp <= 600)
    if shape and "fault_review" in receipt: reviewed_receipt(receipt)
    return shape

def prepare_clean(settings,state,launcher_state,*,check_closed,now=None):
    """Caller holds receipt.lock. Reviewed gate owns all fault recovery writes."""
    now=time.time() if now is None else now
    check_closed()
    if settings.is_symlink() or not settings.is_file():
        raise LaunchError("The existing SteamVR settings file is required")
    marker=settings.with_name("vrserver_crash_timestamp.txt")
    if marker.exists() or marker.is_symlink():
        raise LaunchError("SteamVR crash marker found; review it and use the reviewed retry gate")
    data=json.loads(settings.read_text())
    if data.get("driver_alvr_server",{}).get("blocked_by_safe_mode") is not False:
        raise LaunchError("ALVR safe mode is blocked or unknown; review it before launch")
    receipt_path=state/"retry-receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        receipt=read_private(receipt_path)
        if not valid_receipt(receipt,now):
            raise LaunchError("An expired or invalid receipt is present; review and retire it before another attempt")
        status=launcher_state/"status.json"
        if status.exists() and read_private(status).get("event")=="failed" and not reviewed_receipt(receipt):
            raise LaunchError("The previous launcher attempt failed; obtain a reviewed retry receipt")
        return receipt
    status=launcher_state/"status.json"
    if status.exists() and read_private(status).get("event")=="failed":
        raise LaunchError("The previous launcher attempt failed. Review the saved status and use the reviewed retry gate")
    directory(state)
    directory(launcher_state)
    evidence=launcher_state/"clean-start.json"
    write_private(evidence,{"created_at":now,"closed":True,"crash_marker_present":False,
                            "alvr_blocked":False,"settings_changed":False})
    receipt={"created_at":now,"appid":250820,"attempts":1,"clean_start":True,
             "clean_evidence":str(evidence),"safe_mode_was_blocked":False,"automatic_restart":False}
    write_private(receipt_path,receipt)
    return receipt
