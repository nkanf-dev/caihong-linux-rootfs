// SPDX-License-Identifier: MIT
export interface PatchHandle {
  original: Function;
  hasUnpatched: boolean;
  unpatch(): void;
}

export interface HookRuntime {
  router: Record<string, any>;
  managerPrototype: Record<string, any>;
  replacePatch(object: any, property: string, handler: (this: any, args: any[]) => any): PatchHandle;
  wrapPowerElement(element: any, isActive: () => boolean): any;
}

export function isKnownPowerForwarder(fn: unknown): boolean {
  if (typeof fn !== "function") return false;
  // The observed method synchronously forwards its two arguments to the power-menu factory.
  return /^OpenPowerMenu\s*\(\s*([\w$]+)\s*,\s*([\w$]+)\s*\)\s*\{\s*\(0,\s*[\w$]+\.[\w$]+\)\(\s*\1\s*,\s*\2\s*\)\s*;?\s*\}$/.test(fn.toString().trim());
}

export function isKnownPowerRouter(router: any): boolean {
  if (!router || typeof router.OpenPowerMenu !== "function") return false;
  if (isKnownPowerForwarder(router.OpenPowerMenu)) return true;
  // Steam decorates this method with an autobind getter. The class source retains the method body.
  const prototype = Object.getPrototypeOf(router);
  const descriptor = prototype && Object.getOwnPropertyDescriptor(prototype, "OpenPowerMenu");
  if (typeof descriptor?.get !== "function" || typeof prototype?.constructor !== "function") return false;
  const source = prototype.constructor.toString();
  const match = source.match(/OpenPowerMenu\s*\([^)]*\)\s*\{[^{}]*\}/);
  if (!match) return false;
  const candidate = function() {};
  candidate.toString = () => match[0];
  return isKnownPowerForwarder(candidate) && router.OpenPowerMenu.name === "bound OpenPowerMenu" &&
    /\[native code\]/.test(router.OpenPowerMenu.toString());
}

export function isKnownManagerPrototype(prototype: any): boolean {
  if (!prototype || typeof prototype.CreateContextMenuInstance !== "function") return false;
  const fn = prototype.CreateContextMenuInstance;
  const source = fn.toString();
  return fn.length === 5 && source.includes("bCreateHidden") &&
    source.includes("m_setHiddenMenus.add(") && source.includes("m_callbacksMenusChanged.Dispatch(") &&
    ["GetVisibleMenus", "GetAllMenus", "ReleaseHiddenMenu", "ShowMenu", "HideMenu"]
      .every((name) => typeof prototype[name] === "function");
}

export function isScopedPowerElement(element: any, options: any): boolean {
  if (!element || typeof element !== "object" || !element.props || !options) return false;
  if (!Object.keys(element.props).every((key) => key === "onCancel")) return false;
  if (element.props.onCancel !== options.onCancel) return false;
  const type = element.type;
  return typeof type === "function" ||
    (type && typeof type === "object" && (typeof type.type === "function" || typeof type.render === "function"));
}

export function hasNativePowerActions(tree: any, menuType: any): boolean {
  if (!tree || tree.type !== menuType || !Array.isArray(tree.props?.children)) return false;
  const tokens = new Set<string>();
  let count = 0;
  const visit = (node: any, depth: number): void => {
    if (depth > 8 || ++count > 128 || !node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      node.forEach((child) => visit(child, depth + 1));
      return;
    }
    if (typeof node.props?.strDisplayNameLocToken === "string" && typeof node.props?.onSelected === "function") {
      tokens.add(node.props.strDisplayNameLocToken);
    }
    visit(node.props?.children, depth + 1);
  };
  visit(tree.props.children, 0);
  return ["#Shutdown", "#Quit_Shutdown"].some((token) => tokens.has(token)) &&
    ["#Restart", "#Quit_Restart", "#RestartDevice"].some((token) => tokens.has(token));
}

export function installScopedPowerHook(runtime: HookRuntime): () => void {
  const { router, managerPrototype, replacePatch, wrapPowerElement } = runtime;
  if (!isKnownPowerRouter(router) || !isKnownManagerPrototype(managerPrototype)) {
    throw new Error("Unsupported native power-menu runtime shape");
  }
  let active = true;
  let depth = 0;
  const menus = new Set<any>();
  const patches: PatchHandle[] = [];
  try {
    const managerPatch = replacePatch(managerPrototype, "CreateContextMenuInstance", function(args) {
      let changed = false;
      if (active && depth > 0 && isScopedPowerElement(args[0], args[4])) {
        try {
          args[0] = wrapPowerElement(args[0], () => active);
          changed = true;
        } catch (error) {
          console.warn("[ReturnAndroid] Native menu was left unchanged", error);
        }
      }
      const result = managerPatch.original.apply(this, args);
      if (changed && typeof result?.Hide === "function") menus.add(result);
      return result;
    });
    patches.push(managerPatch);
    const routerPatch = replacePatch(router, "OpenPowerMenu", function(args) {
      depth++;
      try {
        return routerPatch.original.apply(this, args);
      } finally {
        depth--;
      }
    });
    patches.push(routerPatch);
  } catch (error) {
    active = false;
    patches.reverse().forEach((patch) => { if (!patch.hasUnpatched) patch.unpatch(); });
    throw error;
  }
  return () => {
    if (!active) return;
    active = false;
    for (const menu of menus) {
      try { menu.Hide(); } catch (error) { console.warn("[ReturnAndroid] Menu close failed", error); }
    }
    menus.clear();
    for (const patch of patches.reverse()) {
      if (!patch.hasUnpatched) patch.unpatch();
    }
  };
}
