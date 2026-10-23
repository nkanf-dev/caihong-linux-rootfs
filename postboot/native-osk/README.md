# Native floating input panel

This KWin patch adds a provider opt-in for a floating native virtual keyboard.
The default docked and overlay paths keep their existing behavior.

Add this key to the selected native provider's desktop entry, beside `Exec`:

```ini
X-KDE-Wayland-VirtualKeyboard-Floating=true
```

KWin reads both values when it loads the selected `Wayland/InputMethod`
desktop file. Reload that provider selection after changing its metadata.
The explicit command-line provider path stays docked.

## Provider surface contract

- Use the existing native input-method/input-panel path, not a normal toplevel.
- Keep one output-sized transparent surface. Move the keyboard's visual items
  inside it when dragging.
- Update the surface input region in the same logical coordinates. Outside
  that region, pointer and touch input must reach the underlying application.
- Match KWin's selected panel output, including the existing
  `ARMADA_VIRTUAL_KEYBOARD_CONNECTOR` override, output scale and rotation.
- Keep the native show/hide and text-input lifecycle.

Only a panel surface from KWin's current dedicated input-method connection
can receive this policy. KWin snapshots it when the panel is constructed and
applies it only to virtual-keyboard mode. A provider change, including a change
of the metadata flag with the same `Exec`, restarts the native provider.

For surface input bounds `R` and output origin `O`, the floating frame is
`R.translated(O)`. The existing frame-to-buffer conversion keeps the buffer
origin at `O` while the input region moves. Floating panels reserve no
application keyboard space and publish empty text-input-v2 overlap. Their
shown state and existing taskbar exclusion remain on the native path.

## Native build and acceptance

Apply `patches/0001-provider-opt-in-floating-input-panel.patch` after both
ARMADA patches on the prepared source described in `PROVENANCE.json`.
Build through that native package's environment and preserve its matching
custom libraries.

Before rollout, verify native integration for:

- Metadata absent/false, explicit command providers and overlays.
- Dedicated-client identity, null/retired clients and constructor snapshots.
- Equal `Exec` with a changed flag, provider replacement and crash restart.
- Mask drag/resize, complex and empty input regions, fractional scaling and
  nonzero/negative output origins.
- Empty application reservation/overlap with accurate visibility, hide/show,
  remap, text input and lock lifecycle.
- Connector selection, output changes/removal, rotation and scale changes.

Provider and package rollback use the prior provider selection and the exact
previous ARMADA KWin package set with its matching libraries.

## Ordered patch series

Apply the five patches after the exact Fedora 6.7.5 source and the retained two Armada patches:

1. `0001-provider-opt-in-floating-input-panel.patch`: default-off provider policy, fixed output buffer, bounded input region and no application reservation.
2. `0002-test-provider-floating-input-panel.patch`: real dedicated-client floating policy and ordinary-client rejection regressions.
3. `0003-input-method-replay-state-on-late-bind.patch`: after binding the active native context, replay its current cached surrounding/content state and a real commit serial. It does not request focus or visibility.
4. `0004-reactivate-unmapped-native-panel-on-show.patch`: explicit system show can recall a provider-unmapped native panel through a fresh context edge. Implicit V3 state updates and panel setup retain their old behavior. Retired preedit/fallback is cancelled without committing it before replacement.
5. `0005-test-native-floating-input-hit-through.patch`: compositor virtual-pointer delivery reaches the underlying application outside the native input mask and the provider inside it, including after mask movement. App keyboard focus/geometry and the full buffer remain unchanged.

`PROVENANCE.json` records exact patch bytes, order and source hashes. Native reverse/forward application with strict whitespace checks reproduced the final build source exactly.

## Causal and real-provider validation

The late-bind test first failed without its implementation while the early-bind control passed. With patch 0003, both and the complete input-method CTest passed. The unmapped recall regression first failed with one activation instead of two. An intermediate patch was rejected because ordinary hidden V3 state updates also reactivated; the final private ShowReason split preserves those updates and passes the preedit/fallback regression plus the complete input-method CTest.

The final private KWin was also exercised as an isolated nested Wayland compositor, not a replacement of the main desktop session. The actual OnHand provider committed a Chinese candidate to its independent scratch client after a standard application-owned show request, with no agent context refresh. Real shared QML grip/resize items moved and resized the keyboard while the native full-output root and input mask stayed coherent. Server frame samples changed while the same buffer remained at the output origin. Actual hide-button unmap and one system-native recall passed after a same-connection asynchronous Wayland sync barrier; local visibility alone cannot order independent D-Bus and Wayland requests.

These are source, protocol and automated-pointer results. Transparent-area compositor pointer routing was subsequently verified with real application/provider pointer resources and moved input masks. Physical touch, the display/output matrix and text-input-v2/internal/nonfloating recall coverage remain open. The main package-owned KWin binary/libraries and live provider selector were not replaced by these tests.

The hit-through regression uses KWin's virtual-device pointer path, not direct QtTest events sent to the provider. Both client queues are dispatched before enter/button assertions. It checks press and release button identity/state, wrong-client event absence, keyboard focus and no application configure. The focused native test and the complete input-method CTest passed. This is not physical pointer or touchscreen acceptance.
