# Rollback

1. Close VRChat normally. Close other Steam games before any compatibility-tool maintenance.
2. In Steam's VRChat properties, restore the saved launch options and compatibility-tool choice.
3. Remove this route's `STEAM_COMPAT_DATA_PATH`, `EAC_LAUNCHERDIR`, and private-launcher invocation from VRChat's launch options if they were absent before setup.
4. Leave the stock Steam FEX tool alone. This route did not replace it, so there is no global FEX copy-back step.
5. Keep `$HOME/.local/share/cvrc-x64` and `$HOME/.local/share/caihong-vrchat-fex-eac-tool` as private rollback assets until the owner decides to remove them. Removing the launch options is enough to stop selecting them.
6. If the original prefix needs restoration, use its owner's saved backup only after Steam is closed. Preserve the current prefix first. The assessment's x86-64 first-run evaluator touched the original prefix after backup.

The launcher does not change the Wine registry or install a Mono override. Do not reapply old diagnostic `RuntimePath` values.

Do not use a global process kill or delete an FEXServer socket while another game is running. The synthetic validator stops only its own staged server with the same private data path. For normal play, close the game and allow its server to exit normally.

No game/EAC patch, host package rollback, binfmt change, service change, kernel change, or network change is part of this route.
