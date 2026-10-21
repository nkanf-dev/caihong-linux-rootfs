# Private VRChat route preservation plan

**Goal:** Preserve the verified desktop route as portable source and small evidence records.
**Scope:** New files below `postboot/vrchat` only. Host-only preparation and tests. No commits.

1. Inspect the source launcher, exact FEX source lock, Steam-mode build, synthetic results, and historical desktop checkpoint.
2. Preserve the build/validation recipe and a small set of synthetic sources. Keep runtime binaries, prefixes, cores, private configuration, and raw logs outside this tree.
3. Adapt the real launcher to `HOME` and the current UID. Keep one exact private-wrapper substitution and the original Armada launch chain. Add fail-closed checks and no argument/environment logging.
4. Test the launcher with mocked `execv` and test build/validation helpers on the host.
5. Write setup, rollback, source provenance, and historical status. Mark desktop EAC 301 verified, later normal closure, and VR/audio pending.
6. Check all files for private paths, stale state claims, and external scratch-file dependencies. Report paths and test results to the parent.

Completed: 38 source/document/evidence files, 24 passing host unit tests, seven passing shell syntax checks. The private-path/IPv4/MAC/UUID scan found no matches. The later authorized VR attempt is preserved as a pending-validation delta; the parent owns newer live-validation records.
