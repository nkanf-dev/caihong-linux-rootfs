/* Custom SteamUI action. Run in the main SteamUI page context. */
async function nativeDesktopMenu(action = "read") {
  const allowed = new Set(["read", "enable", "disable", "open"]);
  if (!allowed.has(action)) throw new Error("Use read, enable, disable, or open");
  if (!window.settingsStore?.GetClientSetting) throw new Error("Steam settings store unavailable");
  const key = "show_switch_to_desktop_at_login";
  const [before, setValue] = window.settingsStore.GetClientSetting(key);
  if (typeof before !== "boolean" || typeof setValue !== "function") {
    throw new Error("Unexpected native setting interface");
  }
  if (action === "enable" || action === "disable") await setValue(action === "enable");
  const after = window.settingsStore.GetClientSetting(key)[0];
  if (typeof after !== "boolean") throw new Error("Native setting readback failed");
  if (action === "open") {
    if (!window.SteamUIStore?.OpenPowerMenu) throw new Error("Native power menu unavailable");
    window.SteamUIStore.OpenPowerMenu(null);
  }
  return {setting: key, before, after};
}
