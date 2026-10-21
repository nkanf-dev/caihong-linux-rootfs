// SPDX-License-Identifier: MIT
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Confirmation, type ConfirmationUI } from "../../src/Confirmation";
import { ReturnConfirmation } from "../../src/confirmation-core";
import { backendErrorMessage } from "../../src/errors";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
const host = (name: string) => (props: any) => createElement(name, props, props.children);
const ui: ConfirmationUI = { ModalRoot: host("modal"), DialogHeader: host("heading"), DialogBodyText: host("text"),
  DialogButton: host("button"), Focusable: host("focusable"), preferredChild: 4 };

async function mounted(confirmWait?: Promise<{ reboot_requested: boolean }>) {
  const calls: string[] = [];
  const session = new ReturnConfirmation({
    async prepare() { calls.push("prepare"); return { token: "token", expires_in: 60 }; },
    async cancel() { calls.push("cancel"); return true; },
    async confirm() { calls.push("confirm"); return confirmWait || { reboot_requested: true }; },
  });
  await session.prepare();
  let closed = 0;
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(createElement(Confirmation, { session, ui, close: () => { closed++; } })); });
  return { calls, session, renderer, closed: () => closed };
}

test("actual view renders without confirm and prefers Cancel; cancel only cancels", async () => {
  const f = await mounted();
  assert.deepEqual(f.calls, ["prepare"]);
  const buttons = f.renderer.root.findAllByType("button");
  assert.equal(buttons[0].props.preferredFocus, true);
  assert.equal(buttons[0].props.children, "取消");
  await act(async () => { buttons[0].props.onClick(); });
  assert.deepEqual(f.calls, ["prepare", "cancel"]);
  assert.equal(f.closed(), 1);
  await act(async () => f.renderer.unmount());
});

test("actual confirm event calls once; rapid repeat and cancel while busy do nothing", async () => {
  let finish!: (value: { reboot_requested: boolean }) => void;
  const pending = new Promise<{ reboot_requested: boolean }>((resolve) => { finish = resolve; });
  const f = await mounted(pending);
  const buttons = f.renderer.root.findAllByType("button");
  await act(async () => { buttons[1].props.onClick(); buttons[1].props.onClick(); buttons[0].props.onClick(); });
  assert.deepEqual(f.calls, ["prepare", "confirm"]);
  assert.equal(f.closed(), 0);
  await act(async () => { finish({ reboot_requested: true }); });
  assert.equal(f.closed(), 1);
  await act(async () => f.renderer.unmount());
});

test("actual view unmount cancels pending confirmation without confirm", async () => {
  const f = await mounted();
  await act(async () => f.renderer.unmount());
  assert.deepEqual(f.calls, ["prepare", "cancel"]);
});

test("phase-specific backend result survives sanitization and unknown errors discourage repetition", () => {
  const message = "Android A 已选为下次启动槽，重启未完成；请在桌面核对后再操作。";
  assert.equal(backendErrorMessage(message), message);
  assert.equal(backendErrorMessage("\u001b未知\n结果"), "未知 结果");
  assert.match(backendErrorMessage(new Error("transport failed")), /勿重复确认/);
});
