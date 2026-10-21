// SPDX-License-Identifier: MIT
export interface PreparedReturn { token: string; expires_in: number; }
export interface ReturnRPC {
  prepare(): Promise<PreparedReturn>;
  cancel(token: string): Promise<boolean>;
  confirm(token: string): Promise<{ reboot_requested: boolean }>;
}

export class ReturnConfirmation {
  private token?: string;
  private preparing = false;
  private confirming = false;
  private disposed = false;
  private expiresAt = 0;

  constructor(private rpc: ReturnRPC, private clock: () => number = Date.now) {}

  async prepare(): Promise<boolean> {
    if (this.disposed || this.preparing || this.confirming || this.token) return false;
    this.preparing = true;
    try {
      const prepared = await this.rpc.prepare();
      if (!prepared || typeof prepared.token !== "string" || !prepared.token ||
          !Number.isFinite(prepared.expires_in) || prepared.expires_in <= 0) {
        throw new Error("Invalid return confirmation response");
      }
      if (this.disposed) {
        await this.rpc.cancel(prepared.token);
        return false;
      }
      this.token = prepared.token;
      this.expiresAt = this.clock() + prepared.expires_in * 1000;
      return true;
    } finally {
      this.preparing = false;
    }
  }

  async cancel(): Promise<void> {
    const token = this.token;
    this.token = undefined;
    if (token && !this.confirming) await this.rpc.cancel(token);
  }

  async confirm(): Promise<boolean> {
    if (this.disposed || this.confirming || !this.token) return false;
    if (this.clock() >= this.expiresAt) {
      await this.cancel();
      throw new Error("Confirmation expired");
    }
    const token = this.token;
    this.token = undefined;
    this.confirming = true;
    try {
      const result = await this.rpc.confirm(token);
      if (result?.reboot_requested !== true) throw new Error("Reboot request was not accepted");
      return true;
    } finally {
      this.confirming = false;
    }
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    await this.cancel();
  }
}
