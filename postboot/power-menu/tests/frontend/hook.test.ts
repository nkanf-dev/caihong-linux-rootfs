// SPDX-License-Identifier: MIT
import assert from "node:assert/strict";
import { test } from "node:test";
import { hasNativePowerActions, installScopedPowerHook, isKnownManagerPrototype, isKnownPowerForwarder, isKnownPowerRouter, type PatchHandle } from "../../src/hook-core";

function mockPatch(object: any, property: string, handler: (this: any, args: any[]) => any): PatchHandle {
  const patch: PatchHandle = {
    original: object[property], hasUnpatched: false,
    unpatch() { object[property] = patch.original; patch.hasUnpatched = true; },
  };
  object[property] = function(...args: any[]) { return handler.call(this, args); };
  return patch;
}

function fixture() {
  const created: any[] = [];
  class Manager {
    m_setHiddenMenus = new Set();
    m_callbacksMenusChanged = { Dispatch() {} };
    CreateContextMenuInstance(element: any, _parent: any, _x: any, _y: any, options: any) {
      const result = { element, hidden: false, Hide() { this.hidden = true; } };
      if (options?.bCreateHidden) {
        this.m_setHiddenMenus.add(result);
        this.m_callbacksMenusChanged.Dispatch();
      }
      created.push(result);
      return result;
    }
    GetVisibleMenus() {} GetAllMenus() {} ReleaseHiddenMenu() {} ShowMenu() {} HideMenu() {}
  }
  const manager = new Manager();
  const element = { type: { type: function Power() {} }, props: { onCancel: undefined } };
  const target = { OpenPowerMenu(e: any, t: any) { return re(e, t); } };
  function re(e: any, t: any) { return manager.CreateContextMenuInstance(element, e, undefined, undefined, { onCancel: t }); }
  // Preserve the exact observed synchronous Steam method shape.
  target.OpenPowerMenu.toString = () => "OpenPowerMenu(e,t){(0,Ue.d4)(e,t)}";
  let wraps = 0;
  const cleanup = installScopedPowerHook({ router: target, managerPrototype: Manager.prototype, replacePatch: mockPatch,
    wrapPowerElement(node) { wraps++; return { ...node, injected: true }; },
  });
  return { target, manager, element, created, cleanup, wraps: () => wraps };
}

test("known forwarder only; async or expanded implementations fail closed", () => {
  const known = function() {}; known.toString = () => "OpenPowerMenu(e,t){(0,Ue.d4)(e,t)}";
  assert.equal(isKnownPowerForwarder(known), true);
  assert.equal(isKnownPowerForwarder(async function OpenPowerMenu() {}), false);
  assert.equal(isKnownPowerForwarder(function OpenPowerMenu() { return 1; }), false);
  assert.equal(isKnownManagerPrototype({ CreateContextMenuInstance() {} }), false);
});

test("no patch effects until native power invocation; unrelated menus unchanged", () => {
  const f = fixture();
  assert.equal(f.created.length, 0);
  f.manager.CreateContextMenuInstance(f.element, null, null, null, { onCancel: undefined });
  assert.equal(f.wraps(), 0);
  const result = f.target.OpenPowerMenu(null, undefined);
  assert.equal(f.wraps(), 1);
  assert.equal(result.element.injected, true);
  assert.equal(f.element.hasOwnProperty("injected"), false);
  f.cleanup();
});

test("cleanup removes hooks and closes injected menus; repeated cleanup is safe", () => {
  const f = fixture();
  const result = f.target.OpenPowerMenu(null, undefined);
  f.cleanup(); f.cleanup();
  assert.equal(result.hidden, true);
  f.target.OpenPowerMenu(null, undefined);
  assert.equal(f.wraps(), 1);
});

test("render guard requires native Menu plus both shutdown and restart action tokens", () => {
  const menu = {};
  const action = (token: string) => ({ props: { strDisplayNameLocToken: token, onSelected() {} } });
  const native = { type: menu, props: { children: [action("#Quit_Shutdown"), false, action("#Quit_Restart")] } };
  assert.equal(hasNativePowerActions(native, menu), true);
  assert.equal(hasNativePowerActions(native, {}), false);
  assert.equal(hasNativePowerActions({ ...native, props: { children: [action("#Shutdown")] } }, menu), false);
  assert.equal(hasNativePowerActions({ type: menu, props: { children: "Power" } }, menu), false);
});


test("observed autobind getter is validated through retained class method source", () => {
  const Klass = class { OpenPowerMenu(_e: any, _t: any) {} };
  Klass.toString = () => "class SteamRouter{OpenPowerMenu(e,t){(0,Ue.d4)(e,t)}}";
  const original = function OpenPowerMenu() {};
  Object.defineProperty(Klass.prototype, "OpenPowerMenu", { configurable: true, get() { return original.bind(this); } });
  const router = new Klass();
  assert.equal(isKnownPowerRouter(router), true);
  Klass.toString = () => "class SteamRouter{OpenPowerMenu(e,t){return somethingElse(e,t)}}";
  assert.equal(isKnownPowerRouter(router), false);
});
