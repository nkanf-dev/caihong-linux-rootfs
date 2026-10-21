# PCVR copied-source licenses

`provenance.json` maps copied paths and license texts to their pinned upstream source.

| Component | License text | Scope |
| --- | --- | --- |
| ALVR Vulkan layer | `ALVR-vulkan-layer-MIT.txt` | Layer sources, source copies, and patch-derived layer code |
| ALVR server protocol header | `ALVR-MIT.txt` | `build/source/alvr/server_openvr/cpp/platform/linux/protocol.h` |
| picojson | `picojson-BSD-2-Clause.txt` | Bundled picojson header; original notice also remains in the header |
| Vulkan-Headers | `Vulkan-Headers/LICENSE.md`, `LICENSES/Apache-2.0.txt`, `LICENSES/MIT.txt` below that directory | Pinned externally staged headers, following their individual SPDX notices |

Vulkan header bodies are fetched outside the repository. Their license texts are retained here and fetched again with the header stage. Local test stubs and replay adaptations are identified in `provenance.json`; they do not contain captured memory.
