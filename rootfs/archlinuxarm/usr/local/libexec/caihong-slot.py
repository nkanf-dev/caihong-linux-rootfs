#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixed reviewed slot roles. Importing this file performs no I/O."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib

CONFIG = Path("/etc/caihong-slot.json")
SELF = Path("/usr/local/libexec/caihong-slot.py")
LAUNCHER = Path("/usr/local/sbin/caihong-slot")
QBOOT = "/usr/local/sbin/qbootctl"
SYSTEMCTL = "/usr/bin/systemctl"
BUS = "/usr/bin/busctl"
FINDMNT = "/usr/bin/findmnt"
LOGIN = ["org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager"]
PAIR_NAMES = ("abl", "aop", "apdp", "cmnlib", "cmnlib64", "devcfg", "dtbo", "hyp",
              "keymaster", "msadp", "qupfw", "storsec", "tz", "vbmeta", "vbmeta_system",
              "boot", "system", "vendor", "modem", "system_ext", "product")


class SwitchError(RuntimeError):
    pass


def event(phase, **fields):
    """Bounded JSON is written to stderr and the existing journal socket."""
    line = json.dumps({"phase": phase, **fields}, ensure_ascii=False, separators=(",", ":"))[:12000]
    print(line, file=sys.stderr, flush=True)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            stream.settimeout(0.2)
            stream.connect("/run/systemd/journal/socket")
            stream.send(("PRIORITY=5\nSYSLOG_IDENTIFIER=caihong-slot\nMESSAGE=" + line).encode())
    except OSError:
        pass


def trusted_file(path, executable=False):
    path = Path(path)
    if not path.is_absolute():
        raise SwitchError("系统文件路径必须为绝对路径")
    for part in [path, *path.parents]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SwitchError("系统文件所有者、权限或路径检查失败：" + str(part))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
        raise SwitchError("系统文件类型或大小异常：" + str(path))
    if executable and not os.access(path, os.X_OK):
        raise SwitchError("系统工具无法执行：" + str(path))
    return path.read_bytes()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SwitchError("配置包含重复字段")
        result[key] = value
    return result


def validate_config(cfg):
    keys = {"schema", "approved", "android_slot", "linux_slot", "linux_partlabel", "linux_bytes",
            "kernel_release", "qbootctl_sha256", "ufs_boot_lun_path"}
    if not isinstance(cfg, dict) or set(cfg) != keys:
        raise SwitchError("启动配置字段不匹配")
    if type(cfg["schema"]) is not int or cfg["schema"] != 1 or type(cfg["approved"]) is not bool:
        raise SwitchError("启动配置版本或批准状态无效")
    if (cfg["android_slot"], cfg["linux_slot"]) != ("a", "b"):
        raise SwitchError("此配置仅支持已核对的 Android A / Linux B")
    if cfg["linux_partlabel"] != "linux" or type(cfg["linux_bytes"]) is not int or cfg["linux_bytes"] != 68719476736:
        raise SwitchError("Linux 分区身份配置不符")
    if not isinstance(cfg["kernel_release"], str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,128}", cfg["kernel_release"]):
        raise SwitchError("Linux 内核配置无效")
    if not isinstance(cfg["qbootctl_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", cfg["qbootctl_sha256"]):
        raise SwitchError("qbootctl 校验值无效")
    lun_path = cfg["ufs_boot_lun_path"]
    if not isinstance(lun_path, str) or not lun_path.startswith("/sys/devices/") or not lun_path.endswith("/attributes/boot_lun_enabled") or ".." in Path(lun_path).parts:
        raise SwitchError("UFS 只读属性路径无效")
    return cfg


def load_config():
    try:
        return validate_config(json.loads(trusted_file(CONFIG), object_pairs_hook=no_duplicate_keys))
    except (OSError, ValueError, TypeError) as exc:
        raise SwitchError("无法读取已核对的启动配置") from exc


def verify_tools(cfg):
    trusted_file(SELF)
    trusted_file(LAUNCHER, executable=True)
    tool = trusted_file(QBOOT, executable=True)
    if hashlib.sha256(tool).hexdigest() != cfg["qbootctl_sha256"]:
        raise SwitchError("qbootctl 与已核对配置不匹配")
    for path in [SYSTEMCTL, BUS, FINDMNT]:
        trusted_file(path, executable=True)


def run_command(argv, timeout):
    """No shell or inherited environment. Timeout never authorizes a retry."""
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       env={"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "LANG": "C", "LC_ALL": "C"},
                                       start_new_session=True)
            timed_out = False
            try:
                process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    event("tool_cleanup_pending", tool=argv[0], pid=process.pid)
            out.seek(0); err.seek(0)
            stdout = out.read(65537); stderr = err.read(65537)
            event("tool_result", argv=argv, returncode=process.returncode, timeout=timed_out,
                  stderr=stderr[:8192].decode("utf-8", "replace"))
            if timed_out:
                raise SwitchError("系统工具超时；操作状态需重新核对")
            if len(stdout) > 65536 or len(stderr) > 65536:
                raise SwitchError("系统工具输出过多")
            if process.returncode != 0:
                raise SwitchError("系统工具失败：" + argv[0])
            return stdout.decode("utf-8", "strict").strip()
    except (OSError, UnicodeError) as exc:
        raise SwitchError("无法执行或读取系统工具：" + argv[0]) from exc


def read_text(path, limit=65536):
    with open(path, "rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SwitchError("系统身份文件过大")
    return data.decode("utf-8", "strict").replace("\0", "").strip()


def check_boot_parameters(cmdline, bootconfig, linux_slot, partlabel):
    roots = re.findall(r"(?:^|\s)root=([^\s]+)", cmdline)
    if roots != ["PARTLABEL=" + partlabel]:
        raise SwitchError("Linux 根启动参数与已核对分区不符")
    suffixes = re.findall(r"(?:^|\s)(?:androidboot\.)?slot_suffix=([^\s]+)", cmdline)
    suffixes += re.findall(r'(?m)^\s*(?:androidboot\.)?slot_suffix\s*=\s*"?([^"\s]+)"?\s*$', bootconfig)
    if any(value != "_" + linux_slot for value in suffixes):
        raise SwitchError("真实启动槽参数与 Linux B 配置冲突")


def read_identity(cfg):
    boot_id = read_text("/proc/sys/kernel/random/boot_id")
    try:
        uuid.UUID(boot_id)
    except ValueError as exc:
        raise SwitchError("启动身份无效") from exc
    kernel = os.uname().release
    if kernel != cfg["kernel_release"]:
        raise SwitchError("当前 Linux 内核与已核对配置不符")
    cmdline = read_text("/proc/cmdline")
    bootconfig = read_text("/proc/bootconfig") if Path("/proc/bootconfig").exists() else ""
    check_boot_parameters(cmdline, bootconfig, cfg["linux_slot"], cfg["linux_partlabel"])
    mounts = json.loads(run_command([FINDMNT, "--json", "--target", "/", "--output", "SOURCE,FSTYPE,MAJ:MIN"], 5))
    rows = mounts.get("filesystems", [])
    if len(rows) != 1 or rows[0].get("fstype") != "ext4":
        raise SwitchError("当前根文件系统不是预期 ext4 分区")
    source = rows[0].get("source", "")
    device = Path(source).resolve(strict=True)
    if not re.fullmatch(r"/dev/sd[a-z][0-9]+", str(device)):
        raise SwitchError("根文件系统不是已核对的直接块分区")
    info = device.stat()
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.stat("/").st_dev:
        raise SwitchError("根设备身份不匹配")
    sysblock = Path("/sys/class/block") / device.name
    properties = dict(line.split("=", 1) for line in read_text(sysblock / "uevent").splitlines() if "=" in line)
    size = int(read_text(sysblock / "size")) * 512
    if properties.get("PARTNAME") != cfg["linux_partlabel"] or size != cfg["linux_bytes"]:
        raise SwitchError("根分区 PARTNAME 或 64 GiB 容量不符")
    if read_text(sysblock / "dev") != f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}":
        raise SwitchError("根设备 sysfs 身份不符")
    if (Path("/dev/disk/by-partlabel") / cfg["linux_partlabel"]).resolve(strict=True) != device:
        raise SwitchError("Linux 分区标签链接指向不符")
    return {"boot_id": boot_id, "root_device": str(device), "root_dev": [os.major(info.st_rdev), os.minor(info.st_rdev)],
            "root_bytes": size, "partlabel": properties["PARTNAME"], "kernel_release": kernel}


def parse_gpt(read, disk_bytes, block):
    if block not in {512, 4096} or disk_bytes % block or disk_bytes < block * 6:
        raise SwitchError("GPT 块设备尺寸无效")
    final_lba = disk_bytes // block - 1
    def header(lba, other):
        data = read(lba * block, block)
        if len(data) != block or data[:8] != b"EFI PART":
            raise SwitchError("GPT 签名或读取长度无效")
        revision, size, crc, reserved = struct.unpack_from("<IIII", data, 8)
        if revision != 0x10000 or size != 92 or reserved != 0:
            raise SwitchError("GPT header 格式不受支持")
        check = bytearray(data[:size]); check[16:20] = bytes(4)
        if zlib.crc32(check) != crc:
            raise SwitchError("GPT header CRC 不符")
        current, backup, first, last = struct.unpack_from("<QQQQ", data, 24)
        start, count, width, array_crc = struct.unpack_from("<QIII", data, 72)
        total = count * width
        if (current, backup) != (lba, other) or first > last or not 1 <= count <= 4096 or width != 128 or total > 1024 * 1024:
            raise SwitchError("GPT 几何或条目格式无效")
        end = start * block + total
        if start < 2 or end > disk_bytes or (lba == 1 and end > first * block) or (lba == final_lba and (start <= last or end > final_lba * block)):
            raise SwitchError("GPT 条目范围无效")
        array = read(start * block, total)
        if len(array) != total or zlib.crc32(array) != array_crc:
            raise SwitchError("GPT partition array CRC 不符")
        return data, array, [first, last, data[56:72].hex(), count, width]
    primary, array, identity = header(1, final_lba)
    backup, backup_array, backup_identity = header(final_lba, 1)
    if array != backup_array or identity != backup_identity:
        raise SwitchError("GPT 主备分区表不一致")
    entries = {}
    for offset in range(0, len(array), 128):
        entry = array[offset:offset + 128]
        if entry[:16] == bytes(16):
            continue
        name = entry[56:128].decode("utf-16-le", "strict").split("\0", 1)[0]
        first, last = struct.unpack_from("<QQ", entry, 32)
        if not name or name in entries or first > last or first < identity[0] or last > identity[1]:
            raise SwitchError("GPT 分区名称或范围无效")
        entries[name] = entry
    return {"entries": entries, "identity": identity + [disk_bytes, block]}


def read_disk(device):
    info = device.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise SwitchError("GPT 目标不是块设备")
    with device.open("rb", buffering=0) as stream:
        block = struct.unpack("I", fcntl.ioctl(stream.fileno(), 0x1268, bytes(4)))[0]
        size = struct.unpack("Q", fcntl.ioctl(stream.fileno(), 0x80081272, bytes(8)))[0]
        return parse_gpt(lambda offset, count: os.pread(stream.fileno(), count, offset), size, block)


def selection_from_attributes(attrs, pairs, lun):
    active = None
    for base in pairs:
        a, b = attrs[base + "_a"], attrs[base + "_b"]
        flags_a, flags_b = (a >> 48) & 255, (b >> 48) & 255
        selected = "a" if flags_a & 4 else "b"
        if bool(flags_a & 4) == bool(flags_b & 4) or (active is not None and selected != active):
            raise SwitchError("各 GPT A/B active 标志不一致")
        active = selected
    if active not in {"a", "b"} or lun != (1 if active == "a" else 2):
        raise SwitchError("GPT active 与 UFS boot LUN 不一致")
    return {"active": active, "ufs_lun": lun,
            "bootable": {slot: not bool((attrs["boot_" + slot] >> 48) & 128) for slot in ["a", "b"]},
            "successful": {slot: bool((attrs["boot_" + slot] >> 48) & 64) for slot in ["a", "b"]}}


def read_state(cfg):
    partitions = {}
    disks = {}
    pairs = []
    by_label = Path("/dev/disk/by-partlabel")
    for base in PAIR_NAMES:
        paths = [by_label / (base + "_" + slot) for slot in ["a", "b"]]
        present = [path.exists() for path in paths]
        if not any(present):
            if base in {"boot", "dtbo"}:
                raise SwitchError("缺少必要的 boot/dtbo 分区")
            continue
        if not all(present):
            raise SwitchError("A/B 分区不成对：" + base)
        pairs.append(base)
        for slot, path in zip(["a", "b"], paths):
            resolved = path.resolve(strict=True)
            if not re.fullmatch(r"/dev/sd[a-z][0-9]+", str(resolved)) or not stat.S_ISBLK(resolved.stat().st_mode):
                raise SwitchError("分区链接目标无效")
            disk = Path(re.sub(r"[0-9]+$", "", str(resolved)))
            disks[str(disk)] = disk
            partitions[base + "_" + slot] = str(disk)
    tables = {name: read_disk(device) for name, device in disks.items()}
    attrs = {}
    for name, disk in partitions.items():
        if name not in tables[disk]["entries"]:
            raise SwitchError("GPT 未包含预期分区：" + name)
        attrs[name] = struct.unpack_from("<Q", tables[disk]["entries"][name], 48)[0]
    path = Path(cfg["ufs_boot_lun_path"])
    if path.resolve(strict=True) != path or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise SwitchError("UFS 属性路径或权限不符")
    if not stat.S_ISREG(path.stat().st_mode):
        raise SwitchError("UFS 属性类型无效")
    lun = int(read_text(path), 0)
    result = selection_from_attributes(attrs, pairs, lun)
    return {**result, "tables": tables, "pairs": pairs, "partitions": partitions}


def verify_transition(before, after):
    if before["pairs"] != after["pairs"] or set(before["tables"]) != set(after["tables"]):
        raise SwitchError("切换期间分区集合发生变化")
    mutable = {base + "_" + slot for base in before["pairs"] for slot in ["a", "b"]}
    for disk, table in before["tables"].items():
        other = after["tables"][disk]
        if table["identity"] != other["identity"] or set(table["entries"]) != set(other["entries"]):
            raise SwitchError("切换期间 GPT 几何或分区集合发生变化")
        for name, entry in table["entries"].items():
            newer = other["entries"][name]
            if name in mutable:
                # qbootctl changes only type GUID and the A/B attribute byte.
                if entry[16:54] + entry[55:] != newer[16:54] + newer[55:]:
                    raise SwitchError("切换期间分区布局发生变化")
            elif entry != newer:
                raise SwitchError("非目标分区元数据发生变化")


def bus_value(argv, signature):
    message = json.loads(run_command([BUS, "--system", "--json=short", *argv], 5))
    if not isinstance(message, dict) or set(message) != {"type", "data"} or message["type"] != signature or not isinstance(message["data"], list) or len(message["data"]) != 1:
        raise SwitchError("login1 返回格式无效")
    return message["data"][0]


def check_inhibitors(rows):
    if not isinstance(rows, list):
        raise SwitchError("关机保护状态格式无效")
    for row in rows:
        if not isinstance(row, list) or len(row) != 6 or not all(type(v) is str for v in row[:4]) or not all(type(v) is int and 0 <= v < 2 ** 32 for v in row[4:]) or row[3] not in {"block", "delay", "block-weak"}:
            raise SwitchError("关机保护条目格式无效")
        if "shutdown" in row[0].split(":"):
            event("shutdown_inhibitor", who=row[1], why=row[2], mode=row[3])
            raise SwitchError("有程序正在等待或阻止关机，请先保存并关闭程序")


def reboot_ready():
    if bus_value(["call", *LOGIN, "CanReboot"], "s") != "yes":
        raise SwitchError("系统暂不允许普通重启")
    check_inhibitors(bus_value(["call", *LOGIN, "ListInhibitors"], "a(ssssuu)"))
    for prop, signature, expected in [("PreparingForShutdown", "b", False), ("ScheduledShutdown", "(st)", ["", 0]),
                                      ("RebootToFirmwareSetup", "b", False), ("RebootToBootLoaderMenu", "t", 18446744073709551615),
                                      ("RebootToBootLoaderEntry", "s", "")]:
        value = bus_value(["get-property", *LOGIN, prop], signature)
        if type(value) is not type(expected) or value != expected:
            raise SwitchError("系统已有电源操作或特殊启动设置：" + prop)
    # Also checks support for --check-inhibitors without scheduling a reboot.
    run_command([SYSTEMCTL, "--check-inhibitors=yes", "is-system-running"], 5)


def switch(cfg, target, reboot):
    if cfg["approved"] is not True:
        raise SwitchError("请先核对并批准 Android A / Linux B 配置")
    attempted = False
    verified = False
    written = False
    try:
        verify_tools(cfg)
        identity = read_identity(cfg)
        before = read_state(cfg)
        if not before["bootable"][target]:
            raise SwitchError("目标启动槽不可启动")
        already = before["active"] == target
        if not already and target == cfg["android_slot"] and not before["successful"][target]:
            raise SwitchError("Android A 尚未确认启动成功")
        event("preflight_ok", identity=identity, active=before["active"], target=target, ufs_lun=before["ufs_lun"], reboot=reboot)
        if reboot:
            reboot_ready()
        if read_identity(cfg) != identity:
            raise SwitchError("当前 Linux 运行身份发生变化")
        if not already:
            attempted = True
            event("selection_started", target=target)
            run_command([QBOOT, "-s", target], 20)
            written = True
        after = read_state(cfg)
        verify_transition(before, after)
        if after["active"] != target or not after["bootable"][target]:
            raise SwitchError("选槽读回未通过")
        if read_identity(cfg) != identity:
            raise SwitchError("选槽后 Linux 运行身份发生变化")
        verified = True
        event("selection_verified", target=target, ufs_lun=after["ufs_lun"], selection_written=written, boot_id=identity["boot_id"])
        if reboot:
            reboot_ready()
            if read_identity(cfg) != identity:
                raise SwitchError("请求重启前 Linux 运行身份发生变化")
            final = read_state(cfg)
            verify_transition(after, final)
            if final["active"] != target or not final["bootable"][target]:
                raise SwitchError("请求重启前启动槽发生变化")
            event("reboot_requested", target=target, boot_id=identity["boot_id"])
            run_command([SYSTEMCTL, "--check-inhibitors=yes", "reboot"], 15)
        return {"target": target, "selection_written": written, "reboot_requested": reboot,
                "boot_id": identity["boot_id"]}
    except Exception as exc:
        event("operation_stopped", target=target, selection_attempted=attempted, selection_verified=verified, error=str(exc))
        if verified:
            detail = " 目标槽已选为下次启动槽；重启未确认完成，请查看日志后再确认。"
        elif attempted:
            detail = " 启动槽可能已改变；未继续重启，请核对 GPT 与 UFS，勿重复写槽。"
        else:
            detail = " 本次未写启动槽，未请求重启。"
        raise SwitchError(str(exc) + detail) from exc


def acquire_lock():
    path = "/run/caihong-slot.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        os.close(fd)
        raise SwitchError("切换锁权限异常")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise SwitchError("已有启动槽操作正在运行") from exc
    return fd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "android", "linux", "a", "b"], nargs="?", default="status")
    parser.add_argument("--reboot", action="store_true", help="explicitly request ordinary reboot after verification")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SwitchError("caihong-slot 只能由 Linux root 运行")
    cfg = load_config()
    verify_tools(cfg)
    if args.command == "status":
        if args.reboot:
            parser.error("status cannot reboot")
        identity = read_identity(cfg)
        state = read_state(cfg)
        print(json.dumps({"approved": cfg["approved"], "mapping": {"android": "a", "linux": "b"},
                          "running_linux": identity, "active": state["active"], "ufs_lun": state["ufs_lun"],
                          "bootable": state["bootable"], "successful": state["successful"]}, ensure_ascii=False, indent=2))
        return
    target = cfg[args.command + "_slot"] if args.command in {"android", "linux"} else args.command
    lock = acquire_lock()
    try:
        print(json.dumps(switch(cfg, target, args.reboot), ensure_ascii=False))
    finally:
        os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        event("failed", error=str(error))
        raise SystemExit(1)
