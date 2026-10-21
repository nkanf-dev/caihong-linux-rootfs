# Desktop and proxy preservation plan

## Scope

Preserve custom post-boot fixes under `postboot/desktop` and `postboot/proxy`.
Keep the original kernel, image, and build files unchanged.
Do not copy binaries, subscriptions, account configuration, raw logs, or private device identifiers.
Parent agent reviews and commits the result.

## Files and checks

1. Preserve the custom pen bridge, its unit, and its pure host tests.
   Add explicit user-session install/remove commands with no fixed user ID.
2. Save the native Steam setting setter as a small JavaScript action with read/enable/disable modes.
   Add a paired-device-only Bluetooth trust/reconnect helper with no stored address.
3. Save the Decky/Mihomo compatibility override as a secret-free template.
   Add a narrow config editor and authenticated loopback-only HK selector.
   Save the Armada service-preservation drop-in without copying third-party implementation code.
4. Document setup, rollback, upstream provenance, HK download region, recorded results, and remaining session-start check.
5. Run pure unit tests, Python compile/CLI checks, JavaScript syntax checks, and template/secret/path review on the host.
   Do not run installation, service, Bluetooth, controller API, or routing actions.

## Completion

All five preservation steps are complete. See `VALIDATION.md` for host checks and
`../docs/desktop-proxy.md` for setup, rollback, recorded state, and deferred device checks.
