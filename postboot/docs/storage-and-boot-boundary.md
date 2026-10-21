# Storage and boot boundary

The rootfs booted after the earlier scoped AVB, ext4 repair, and root filesystem growth work.
Keep the original boot images, AVB backup, GPT/partition metadata, and verified installation records in private durable storage.
Do not commit those images or remove them during repository cleanup.
Use the repository's existing installation and build documentation for partition and boot procedures.

## Temporary UFS queue mitigation

The recorded high-I/O fault included `OCS4`, UPIU response-size mismatch, and `TASK_SET_FULL`.
The root ext4 filesystem was writable with errors_count 0.
Queue depth changed from 63 to 16 for a bounded diagnostic. Subsequent recorded game loads produced no new error relative to that checkpoint.
The setting is volatile. It is not a persistent hardware repair.

`tools/storage_queue.py` reads an explicitly identified sysfs queue file by default.
A write requires a confirmation flag and a private record of the old value.
Identify the correct whole-disk device and resolve its actual sysfs `queue_depth` path first.
Do not copy a guessed path from another device.

```sh
python3 postboot/tools/storage_queue.py /sys/devices/<exact-device-path>/queue_depth
# Only after a new reviewed diagnostic authorizes this write:
sudo python3 postboot/tools/storage_queue.py /sys/devices/<exact-device-path>/queue_depth \
  --set 16 --confirm-volatile-diagnostic --record /path/to/private/queue-change.json
```

For rollback, read the private record's `before` value and apply that value with a new record.
A reboot also resets this volatile setting to the driver's default.
Do not turn it into a udev or boot-time rule from this evidence.
Do not run I/O stress, fsck, partition edits, or boot writes as part of PCVR recovery.
