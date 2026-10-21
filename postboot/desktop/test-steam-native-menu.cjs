const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, 'steam-native-desktop-menu.js'), 'utf8');

function context() {
  let value = false;
  let opens = 0;
  const state = {window: {
    settingsStore: {GetClientSetting(key) {
      assert.equal(key, 'show_switch_to_desktop_at_login');
      return [value, async next => { value = next; }];
    }},
    SteamUIStore: {OpenPowerMenu(argument) { assert.equal(argument, null); opens++; }}
  }};
  vm.createContext(state);
  vm.runInContext(source, state);
  return {state, value: () => value, opens: () => opens};
}

test('read, native setter, readback, and rollback', async () => {
  const c = context();
  assert.equal((await c.state.nativeDesktopMenu('read')).after, false);
  assert.equal((await c.state.nativeDesktopMenu('enable')).after, true);
  assert.equal(c.value(), true);
  assert.equal((await c.state.nativeDesktopMenu('disable')).after, false);
  assert.equal(c.opens(), 0);
});

test('open only opens the native menu and does not change the setting', async () => {
  const c = context();
  await c.state.nativeDesktopMenu('open');
  assert.equal(c.opens(), 1);
  assert.equal(c.value(), false);
});

test('unknown action and unavailable store are refused', async () => {
  const c = context();
  await assert.rejects(c.state.nativeDesktopMenu('switch'), /Use read/);
  c.state.window.settingsStore = null;
  await assert.rejects(c.state.nativeDesktopMenu('enable'), /unavailable/);
});
