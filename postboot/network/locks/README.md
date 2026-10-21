# Exact custom-package update holds

This file-only tool adds 39 exact package names to `[main] excludepkgs`.

- 33 names cover the surviving Armada builds and the three custom packages replaced by DNF40.
- Six Mesa runtime names hold the current Fedora assembly baseline. Their original Armada restoration is pending a graphics/runtime/devel compatibility plan. They are not reported as restored.
- Existing exclusions remain intact. No wildcard or broad security-package freeze is added.
- No DNF, device, network, or service command is called by this tool.

Plan, then apply on native Linux as root:

```sh
sudo python3 lock_caihong_custom_packages.py
sudo python3 lock_caihong_custom_packages.py --apply
```

The apply JSON reports the private receipt path. Save it. Plan or apply rollback using that receipt:

```sh
sudo python3 lock_caihong_custom_packages.py --rollback /var/lib/caihong/package-hold-backups/hold-<id>/receipt.json
sudo python3 lock_caihong_custom_packages.py --rollback /var/lib/caihong/package-hold-backups/hold-<id>/receipt.json --apply
```

Rollback restores the exact prior config bytes and recorded mode/owner/xattrs/times. It refuses to overwrite later config changes. Apply is idempotent. Planning does not create files. Backups/receipts use private directories and files; data and directory entries are fsynced before replacement. File paths are traversed through no-follow directory descriptors. Apply and rollback share an advisory lock with this tool only. Keep other root config writers quiet through the final check-to-rename interval.

Ambiguous duplicate sections/keys, multiline or inline-comment exclusion values, and the `exclude` alias require manual review rather than guessing precedence. Normal unrelated settings and existing comments/line endings are preserved.

The root operator must inspect installed DNF5 help before choosing an explicit per-transaction override for an approved local package restoration. Do not delete the persistent hold just to restore the other two packages. Do not assume an option spelling from DNF4. Confirm a transaction preview changes only the intended local packages; use the exact locally supported exclusion override for that one command. Normal future upgrades must continue to exclude the 39 names.

Host tests (temporary files only):

```sh
python3 -m unittest -v test_lock_caihong_custom_packages
```
