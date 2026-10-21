# Route one Steam audio namespace to ALVR

`route_namespace.py` routes the current VRChat Steam audio namespace to ALVR's connected-headset audio devices. It changes the namespace's two external loopback targets. VRChat keeps its existing namespace playback and capture devices.

The helper uses Python 3 and native `pactl`. It has no third-party Python dependencies.

## Source behavior

ALVR v20.14.1 creates `ALVR Audio` (`Audio/Sink`) and `ALVR Microphone` (`Audio/Source`) while the headset streams. It removes them after disconnect. These nodes are ALVR's PipeWire streams; no extra virtual sink, virtual microphone module, or CPAL device selection is needed.

The supported Linux path is in ALVR tag `v20.14.1`:

- `alvr/server_core/src/connection.rs`: Linux game audio and microphone threads.
- `alvr/audio/src/linux.rs`: creation and callbacks for the sink and source.
- `wiki/Linux-Troubleshooting.md`, section “No audio or microphone”: endpoint selection after connection and removal after disconnect.

WirePlumber 0.5.18 `src/scripts/node/audio-group.lua` creates the namespace devices and external `stream.audio_group:` loopbacks. The helper targets those external streams, preserving the app-to-namespace links.

## Preconditions

1. The device operator has reviewed the current `VRChat.exe` PID and `vrserver` PID.
2. The headset is streaming. Both current ALVR devices belong to that `vrserver`.
3. VRChat has one playback stream and one microphone capture stream in the same Steam audio namespace.
4. Those namespace playback/capture devices currently serve only that reviewed VRChat process. The helper refuses a shared group.
5. Run native Python and pactl as the desktop audio user. Do not run inside FEX, pressure-vessel, or as UID0. The helper pins only its own pactl environment to `/run/user/<current-uid>/pulse/native`; it leaves the game environment alone.

The helper accepts explicit reviewed PIDs. It does not find, start, wake, reconnect, or stop an app or headset.

## Plan, apply, and readback

Run from the `postboot` directory. Set `VRCHAT_PID` and `VRSERVER_PID` to the reviewed current process IDs before using these commands.

```sh
python3 pcvr/audio/route_namespace.py plan   --app-pid "$VRCHAT_PID" --vrserver-pid "$VRSERVER_PID"
```

`plan` reads audio object metadata and prints the two proposed target changes. It makes no audio changes and creates no journal.

After reviewing the plan, create a private state directory and apply one transaction:

```sh
mkdir -p -m 700 "$HOME/.local/state/caihong-pcvr/audio"
python3 pcvr/audio/route_namespace.py apply   --app-pid "$VRCHAT_PID" --vrserver-pid "$VRSERVER_PID"   --journal "$HOME/.local/state/caihong-pcvr/audio/route-1.jsonl"
```

Use a new journal path for each transaction. An existing file is never overwritten. The journal parent must be user-owned and private (0700). The journal is an exclusive, locked, user-owned 0600 regular file.

Before the first move, the helper saves and fsyncs the original endpoints, current object serials, owning client identities, app links, and proposed targets. It rechecks the topology before each move. Each command's start, return code, error output, and target readback are appended and fsynced. The journal is JSON Lines: each complete line is a full transaction snapshot. A crash-truncated final line leaves earlier recovery records intact.

The two commands are native `pactl move-sink-input` and `pactl move-source-output` on the namespace's external streams. If either move or the final readback fails, the helper restores any attempted stream still targeting its recorded ALVR endpoint. It also handles a failed command whose target change did occur. It reports `apply_failed_rollback_incomplete` if topology changes prevent safe compensation.

The helper leaves global defaults, audio daemon configuration, modules, hardware volume, game settings, and headset permissions unchanged. It records object metadata only. It does not capture or record sound or voice.

## Rollback

Use the journal created by the transaction:

```sh
python3 pcvr/audio/route_namespace.py rollback   --journal "$HOME/.local/state/caihong-pcvr/audio/route-1.jsonl"
```

Rollback restores the input first, then output. Before any restore write and before each move, it checks both saved app streams, namespace devices, app-to-namespace links, external loopback streams, owning clients, and exclusive namespace membership. A new group member or changed topology stops automatic recovery and records a manual-review error.

When a current stream still names the recorded ALVR target ID, an endpoint now present at that ID must match the saved endpoint identity and owning vrserver client. A replacement endpoint or owner is left untouched. If the old ALVR endpoint is genuinely absent, rollback can restore the unchanged private namespace to its original target. If PipeWire already restored the exact original target after disconnect, no move is needed. Reused IDs, a third-party target change, or changed namespace identities produce `rollback_incomplete`; inspect `rollback_errors` before taking another action.

Keep the journal until recovery and acceptance are complete. Do not run simultaneous route/rollback operators for one namespace.

## Check the result

1. Inspect the helper's command results and target readbacks.
2. Read native `pactl` or `wpctl status -n` again while the headset streams. The group output must target `ALVR Audio`; its input must read `ALVR Microphone`. VRChat must retain its namespace devices.
3. Inspect active graph links while VRChat produces sound and consumes microphone input. A suspended ALVR endpoint with no linked producer/consumer is expected.
4. Ask the user to check headset playback and the VRChat microphone meter. Do not record voice. Sound and microphone acceptance are separate results.

If the client disconnects before planning or applying, the helper refuses missing ALVR devices. Reconnect only when the user is ready, review current process identities, and run a new plan. There is no background service or automatic persistence in this directory. Repeated manual use can inform a later bounded, per-namespace event handler after the route passes its user checks.

## Host checks

All test pactl responses and moves are mocked:

```sh
python3 -m unittest discover -s pcvr/audio -v
```

The tests cover dynamic IDs, exact app/group/owner matching, missing and ambiguous endpoints, private journal creation before writes, failed/uncertain commands, compensation, disconnect recovery, reused ALVR target IDs, replacement target owners, new output/capture group members, stale serials, changed owners, third-party target changes, and truncated-journal recovery.
