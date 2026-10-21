# SPDX-License-Identifier: MIT
"""Decky backend. Loading this module never runs a command or changes a slot."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import secrets
import stat
import sys
import time

CONFIG = Path("/etc/caihong-power-menu.json")
SLOT = "/usr/local/sbin/caihong-slot"
QBOOT = "/usr/local/sbin/qbootctl"
BUS = "/usr/bin/busctl"
SYSTEMCTL = "/usr/bin/systemctl"
BUS_ARGS = ("--system", "--json=short")
LOGIN = ("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager")
TTL = 45


class SafetyError(RuntimeError):
    pass


def trusted_file(path):
    """Refuse symlinks, non-root ownership, or group/other writable ancestors."""
    path = Path(path)
    if not path.is_absolute():
        raise SafetyError("受信任文件路径必须是绝对路径。")
    for entry in [path, *path.parents]:
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SafetyError("系统文件权限检查失败。")
    if not stat.S_ISREG(path.stat().st_mode):
        raise SafetyError("系统文件类型检查失败。")
    return path.read_bytes()


def deployment():
    try:
        cfg = json.loads(trusted_file(CONFIG))
        if set(cfg) != {"schema", "approved", "android_slot", "linux_slot", "slot_script_sha256", "qbootctl_sha256"}:
            raise ValueError()
        if type(cfg["schema"]) is not int or cfg["schema"] != 1 or cfg["approved"] is not True:
            raise ValueError()
        if (cfg["android_slot"], cfg["linux_slot"]) != ("a", "b"):
            raise ValueError()
        for key, path in [("slot_script_sha256", SLOT), ("qbootctl_sha256", QBOOT)]:
            digest = cfg[key]
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError()
            if hashlib.sha256(trusted_file(path)).hexdigest() != digest:
                raise SafetyError("启动工具已改变，请重新核对安装配置。")
            if not os.access(path, os.X_OK):
                raise SafetyError("启动工具无法执行。")
        return cfg
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SafetyError("请先核对 Android A / Linux B 启动配置。") from exc


async def run_command(*args):
    """Use fixed absolute commands, no shell, no inherited PATH or authorization prompt."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "LANG": "C", "LC_ALL": "C"},
            start_new_session=True,
        )
    except OSError as exc:
        raise SafetyError("系统工具无法启动，请检查安装。") from exc
    async def drain(stream):
        data = bytearray()
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > 65536:
                raise SafetyError("系统检查返回了过多数据。")

    readers = [asyncio.create_task(drain(proc.stdout)), asyncio.create_task(drain(proc.stderr))]
    try:
        stdout, _stderr = await asyncio.wait_for(asyncio.gather(*readers), 15)
        await asyncio.wait_for(proc.wait(), 2)
    except BaseException as exc:
        # Descendants can keep pipes open after the shell leader has exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await proc.wait()
        if isinstance(exc, (asyncio.TimeoutError, asyncio.CancelledError)):
            raise SafetyError("系统操作超时，已停止后续操作。") from exc
        raise
    if proc.returncode != 0:
        raise SafetyError("系统检查或操作失败，已停止后续操作。")
    try:
        return stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise SafetyError("系统检查返回了异常文本。") from exc


def parse_bus(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise SafetyError("无法读取系统重启状态。") from exc


async def bus_call(method):
    return parse_bus(await run_command(BUS, *BUS_ARGS, "call", *LOGIN, method))


def bus_value(message, signature, kind):
    if not isinstance(message, dict) or set(message) != {"type", "data"} or message["type"] != signature:
        raise SafetyError("无法读取系统重启状态。")
    data = message["data"]
    if not isinstance(data, list) or len(data) != 1 or type(data[0]) is not kind:
        raise SafetyError("系统重启状态格式异常。")
    return data[0]


def uint(value, bits):
    return type(value) is int and 0 <= value < 2 ** bits


async def reboot_ready():
    allowed = await bus_call("CanReboot")
    bus_value(allowed, "s", str)
    if allowed != {"type": "s", "data": ["yes"]}:
        raise SafetyError("系统暂不允许重启，请稍后重试。")
    inhibitors = await bus_call("ListInhibitors")
    rows = bus_value(inhibitors, "a(ssssuu)", list)
    for row in rows:
        if not isinstance(row, list) or len(row) != 6 or not all(isinstance(x, str) for x in row[:4]):
            raise SafetyError("无法读取关机保护状态。")
        if row[3] not in {"block", "delay", "block-weak"} or not uint(row[4], 32) or not uint(row[5], 32):
            raise SafetyError("无法读取关机保护状态。")
        if "shutdown" in row[0].split(":"):
            raise SafetyError("有程序正在阻止或等待关机，请先保存并关闭游戏。")
    preparing = parse_bus(await run_command(
        BUS, *BUS_ARGS, "get-property", *LOGIN, "PreparingForShutdown"))
    scheduled = parse_bus(await run_command(
        BUS, *BUS_ARGS, "get-property", *LOGIN, "ScheduledShutdown"))
    preparing_value = bus_value(preparing, "b", bool)
    scheduled_value = bus_value(scheduled, "(st)", list)
    if len(scheduled_value) != 2 or type(scheduled_value[0]) is not str or not uint(scheduled_value[1], 64):
        raise SafetyError("系统重启计划格式异常。")
    if preparing_value or scheduled_value != ["", 0]:
        raise SafetyError("系统已有电源操作，请稍后重试。")
    for prop, expected in [
        ("RebootToFirmwareSetup", {"type": "b", "data": [False]}),
        ("RebootToBootLoaderMenu", {"type": "t", "data": [18446744073709551615]}),
        ("RebootToBootLoaderEntry", {"type": "s", "data": [""]}),
    ]:
        actual = parse_bus(await run_command(BUS, *BUS_ARGS, "get-property", *LOGIN, prop))
        kind = {"b": bool, "t": int, "s": str}[expected["type"]]
        value = bus_value(actual, expected["type"], kind)
        if kind is int and not uint(value, 64):
            raise SafetyError("系统启动方式格式异常。")
        if actual != expected:
            raise SafetyError("系统已设置其他启动方式，请先在桌面核对。")
    state = await run_command(SYSTEMCTL, "--check-inhibitors=yes", "is-system-running")
    if state != "running":
        raise SafetyError("系统服务尚未就绪，请稍后重试。")


async def preflight():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SafetyError("返回 Android 需要 Linux 上的 Decky root 插件权限。")
    if os.environ.get("SERVER_HOST", "127.0.0.1") not in {"127.0.0.1", "::1", "localhost"}:
        raise SafetyError("Decky 必须只监听本机地址，请先检查服务配置。")
    cfg = deployment()
    for tool in [BUS, SYSTEMCTL]:
        trusted_file(tool)
        if not os.access(tool, os.X_OK):
            raise SafetyError("系统工具无法执行，请检查安装。")
    current = await run_command(QBOOT, "-c")
    active = await run_command(QBOOT, "-a")
    if current != "Current slot: _b" or active != "Active slot: _b":
        raise SafetyError("当前启动槽与已核对的 Linux B 配置不符。")
    if await run_command(QBOOT, "-b", cfg["android_slot"]) != "SLOT _a: is marked bootable":
        raise SafetyError("Android A 启动槽不可启动。")
    if await run_command(QBOOT, "-n", cfg["android_slot"]) != "SLOT _a: is marked successful":
        raise SafetyError("Android A 尚未确认启动成功。")
    await reboot_ready()
    return cfg


class Plugin:
    def __init__(self):
        self._pending = None
        self._unloaded = False
        self._busy = False
        self._lock = asyncio.Lock()
        self._task = None

    async def _main(self):
        pass

    async def _unload(self):
        self._unloaded = True
        self._pending = None
        # Do not cancel a confirmed operation halfway through slot selection/readback.
        if self._task is not None:
            await asyncio.shield(self._task)

    async def prepare_return(self):
        async with self._lock:
            if self._unloaded:
                raise SafetyError("插件已停止，请重新打开 Steam 后操作。")
            if self._busy:
                raise SafetyError("返回 Android 正在处理，请勿重复操作。")
            self._pending = None
            await preflight()
            if self._unloaded:
                raise SafetyError("插件已停止，请重新打开 Steam 后操作。")
            token = secrets.token_urlsafe(32)
            self._pending = (token, time.monotonic() + TTL)
            return {"token": token, "expires_in": TTL}

    async def cancel_return(self, token):
        async with self._lock:
            if self._pending and secrets.compare_digest(str(token), self._pending[0]):
                self._pending = None
        return True

    async def confirm_return(self, token):
        async with self._lock:
            pending, self._pending = self._pending, None
            if self._unloaded or self._busy or not pending or not isinstance(token, str):
                raise SafetyError("确认已失效，请重新打开返回 Android。")
            if not secrets.compare_digest(token, pending[0]) or time.monotonic() >= pending[1]:
                raise SafetyError("确认已失效，请重新打开返回 Android。")
            self._busy = True
            self._task = asyncio.create_task(switch_operation())
            self._task.add_done_callback(lambda _task: setattr(self, "_busy", False))
        try:
            return await asyncio.shield(self._task)
        finally:
            # Shield keeps the critical operation alive if the frontend disconnects.
            if self._task.done():
                self._busy = False



async def switch_operation():
    selection_attempted = False
    selection_verified = False
    try:
        await preflight()
        # Existing supported Linux-to-Android script selects and verifies the slot.
        # Separate reboot allows an independent readback before any reboot request.
        selection_attempted = True
        await run_command(SLOT, "android")
        if await run_command(QBOOT, "-a") != "Active slot: _a":
            raise SafetyError("Android 启动槽读回失败，已停止重启。")
        selection_verified = True
        if await run_command(QBOOT, "-c") != "Current slot: _b":
            raise SafetyError("当前启动槽发生变化，已停止重启。")
        if await run_command(QBOOT, "-b", "a") != "SLOT _a: is marked bootable":
            raise SafetyError("Android 启动槽校验失败，已停止重启。")
        await reboot_ready()
        # Enforce inhibitors again in systemctl, including for this root caller.
        # Never force, ignore inhibitors, terminate a game, or auto-retry.
        await run_command(SYSTEMCTL, "--check-inhibitors=yes", "reboot")
        return {"reboot_requested": True}
    except Exception as exc:
        # A selection may already have succeeded. Never hide that state or auto-repair it.
        message = str(exc) if isinstance(exc, SafetyError) else "系统操作失败，已停止后续操作。"
        if selection_verified:
            message += " Android A 已选为下次启动槽，重启未完成；请在桌面核对后再操作。"
        elif selection_attempted:
            message += " 启动槽可能已改变，未请求重启；请先在桌面核对下次启动槽。"
        else:
            message += " 启动槽未改变，未请求重启。"
        raise SafetyError(message) from exc
