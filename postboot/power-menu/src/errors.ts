// SPDX-License-Identifier: MIT
export function backendErrorMessage(error: unknown): string {
  const text = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  // Decky transports Python errors as strings. Keep the phase-specific safety result, not a stack trace.
  const safe = text.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\s+/g, " ").trim();
  if (safe && safe.length <= 768 && /[\u3400-\u9fff]/.test(safe)) return safe;
  return "操作结果未知，请先在桌面核对下次启动槽和系统日志，勿重复确认。";
}
