// SPDX-License-Identifier: MIT
import assert from "node:assert/strict";
import { test } from "node:test";
import { ReturnConfirmation, type ReturnRPC } from "../../src/confirmation-core";

function fixture() {
  const calls: string[] = [];
  const rpc: ReturnRPC = {
    async prepare() { calls.push("prepare"); return { token: "opaque-token", expires_in: 60 }; },
    async cancel(token) { calls.push("cancel:" + token); return true; },
    async confirm(token) { calls.push("confirm:" + token); return { reboot_requested: true }; },
  };
  let now = 0;
  const session = new ReturnConfirmation(rpc, () => now);
  return { calls, rpc, session, expire() { now = 60000; } };
}

test("construction does not contact backend; confirm without prepare does nothing", async () => {
  const f = fixture();
  assert.deepEqual(f.calls, []);
  assert.equal(await f.session.confirm(), false);
  await f.session.dispose();
  assert.deepEqual(f.calls, []);
});

test("entry selection prepares only; cancel never confirms and can run twice", async () => {
  const f = fixture();
  assert.equal(await f.session.prepare(), true);
  assert.deepEqual(f.calls, ["prepare"]);
  await f.session.cancel(); await f.session.cancel();
  assert.equal(await f.session.confirm(), false);
  assert.deepEqual(f.calls, ["prepare", "cancel:opaque-token"]);
});

test("explicit confirmation uses token once", async () => {
  const f = fixture();
  await f.session.prepare();
  assert.equal(await f.session.confirm(), true);
  assert.equal(await f.session.confirm(), false);
  await f.session.dispose();
  assert.deepEqual(f.calls, ["prepare", "confirm:opaque-token"]);
});

test("expired confirmation cancels; no reboot RPC", async () => {
  const f = fixture(); await f.session.prepare(); f.expire();
  await assert.rejects(f.session.confirm(), /expired/);
  assert.deepEqual(f.calls, ["prepare", "cancel:opaque-token"]);
});

test("unload cancels pending token", async () => {
  const f = fixture(); await f.session.prepare(); await f.session.dispose();
  assert.equal(await f.session.confirm(), false);
  assert.deepEqual(f.calls, ["prepare", "cancel:opaque-token"]);
});

test("unload during preparation cancels returned token and prevents dialog", async () => {
  const f = fixture();
  let ready: (value: any) => void = () => {};
  f.rpc.prepare = () => new Promise((resolve) => { ready = resolve; });
  const pending = f.session.prepare(); await f.session.dispose();
  ready({ token: "late-token", expires_in: 60 });
  assert.equal(await pending, false);
  assert.deepEqual(f.calls, ["cancel:late-token"]);
});

test("failed confirm cannot retry its single-use token", async () => {
  const f = fixture(); f.rpc.confirm = async () => { throw new Error("transport failure"); };
  await f.session.prepare(); await assert.rejects(f.session.confirm(), /transport failure/);
  assert.equal(await f.session.confirm(), false);
});
