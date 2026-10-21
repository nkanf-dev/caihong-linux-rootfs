// SPDX-License-Identifier: MIT
import {
  DialogBodyText, DialogButton, DialogHeader, Focusable, Menu, MenuItem,
  ModalRoot, NavEntryPositionPreferences, Router, createReactTreePatcher,
  findModuleExport, replacePatch, showModal,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { cloneElement, isValidElement, type ReactElement } from "react";
import { ReturnConfirmation, type PreparedReturn } from "./confirmation-core";
import { Confirmation } from "./Confirmation";
import { backendErrorMessage } from "./errors";
import { hasNativePowerActions, installScopedPowerHook, isKnownManagerPrototype } from "./hook-core";

const prepare = callable<[], PreparedReturn>("prepare_return");
const cancel = callable<[token: string], boolean>("cancel_return");
const confirm = callable<[token: string], { reboot_requested: boolean }>("confirm_return");
const ENTRY_KEY = "caihong-return-android";
const confirmationUI = { ModalRoot, DialogHeader, DialogBodyText, DialogButton, Focusable,
  preferredChild: NavEntryPositionPreferences.PREFERRED_CHILD };


export default definePlugin(() => {
  let active = true;
  let preparing = false;
  const sessions = new Set<ReturnConfirmation>();
  const dialogs = new Set<{ Close(): void }>();
  let removeHook: (() => void) | undefined;

  const startConfirmation = async () => {
    if (!active || preparing || dialogs.size) return;
    preparing = true;
    const session = new ReturnConfirmation({ prepare, cancel, confirm });
    sessions.add(session);
    try {
      if (!await session.prepare() || !active) return;
      let dialog: { Close(): void };
      const close = () => {
        dialog.Close();
        dialogs.delete(dialog);
        sessions.delete(session);
        void session.dispose().catch(console.error);
      };
      dialog = showModal(<Confirmation session={session} close={close} ui={confirmationUI} />, undefined, {
        strTitle: "返回 Android", bHideMainWindowForPopouts: false, bNeverPopOut: true,
      });
      dialogs.add(dialog);
    } catch (error) {
      console.error("[ReturnAndroid] Could not prepare return", error);
      if (active) toaster.toast({ title: "返回 Android", body: backendErrorMessage(error) });
      await session.dispose().catch(console.error);
      sessions.delete(session);
    } finally {
      preparing = false;
      if (!active) {
        await session.dispose().catch(console.error);
        sessions.delete(session);
      }
    }
  };

  try {
    if (![Menu, MenuItem, ModalRoot, DialogHeader, DialogBodyText, DialogButton, Focusable].every(Boolean)) {
      throw new Error("Native confirmation components are unavailable");
    }
    const Manager = findModuleExport((value: any) => isKnownManagerPrototype(value?.prototype));
    if (!Manager) throw new Error("Native context-menu manager was not found");
    const treePatch = createReactTreePatcher([(tree) => tree], (_args, tree) => {
      if (!active || !hasNativePowerActions(tree, Menu) || !isValidElement(tree)) return tree;
      const element = tree as ReactElement<{ children: any[] }>;
      if (element.props.children.some((child: any) => child?.key === ENTRY_KEY)) return tree;
      return cloneElement(element, {}, [
        ...element.props.children,
        <MenuItem key={ENTRY_KEY} onSelected={() => { if (active) void startConfirmation(); }}>返回 Android</MenuItem>,
      ]);
    }, "CaihongReturnAndroid");
    removeHook = installScopedPowerHook({
      router: Router,
      managerPrototype: Manager.prototype,
      replacePatch,
      wrapPowerElement(element) {
        if (!isValidElement(element)) throw new Error("Invalid native power element");
        return treePatch([], { ...element });
      },
    });
  } catch (error) {
    console.error("[ReturnAndroid] Native power menu was left unchanged", error);
  }

  return {
    name: "返回 Android",
    icon: <span aria-hidden="true">↪</span>,
    onDismount() {
      active = false;
      removeHook?.();
      for (const dialog of dialogs) dialog.Close();
      dialogs.clear();
      for (const session of sessions) void session.dispose().catch(console.error);
      sessions.clear();
    },
  };
});
