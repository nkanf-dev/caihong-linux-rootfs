// SPDX-License-Identifier: MIT
import { useEffect, useRef, useState, type ComponentType } from "react";
import { ReturnConfirmation } from "./confirmation-core";
import { backendErrorMessage } from "./errors";

export interface ConfirmationUI {
  ModalRoot: ComponentType<any>; DialogHeader: ComponentType<any>; DialogBodyText: ComponentType<any>;
  DialogButton: ComponentType<any>; Focusable: ComponentType<any>; preferredChild: number;
}

export function Confirmation({ session, close, ui }: {
  session: ReturnConfirmation; close: () => void; ui: ConfirmationUI;
}) {
  const { ModalRoot, DialogHeader, DialogBodyText, DialogButton, Focusable } = ui;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const busyRef = useRef(false);
  useEffect(() => () => { void session.dispose().catch(console.error); }, [session]);
  const cancelAndClose = () => {
    if (busyRef.current) return;
    void session.cancel().catch(console.error).finally(close);
  };
  const confirmAndReboot = async () => {
    if (busyRef.current || error) return;
    busyRef.current = true;
    setBusy(true);
    try {
      if (await session.confirm()) close();
    } catch (failure) {
      console.error("[ReturnAndroid] Return request failed", failure);
      setError(backendErrorMessage(failure));
      busyRef.current = false;
      setBusy(false);
    }
  };
  return <ModalRoot onCancel={cancelAndClose} bDisableBackgroundDismiss={busy}>
    <DialogHeader>返回 Android</DialogHeader>
    <DialogBodyText>请先保存进度并关闭游戏。确认后，设备将重启并进入 Android。</DialogBodyText>
    {error && <DialogBodyText>{error}</DialogBodyText>}
    <Focusable flow-children="column" navEntryPreferPosition={ui.preferredChild}>
      <DialogButton preferredFocus disabled={busy} onClick={cancelAndClose}>取消</DialogButton>
      <DialogButton disabled={busy || error} onClick={() => { void confirmAndReboot(); }}>
        {busy ? "正在重启…" : "重启并返回 Android"}
      </DialogButton>
    </Focusable>
  </ModalRoot>;
}
