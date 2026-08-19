import { afterEach, describe, expect, it } from "vitest";
import { createDetectedBridgeClient, createHostBridgeClient, hasHostBridge } from "./client";
import type { BridgeRequest, BridgeTransport } from "./contracts";

describe("bridge transport framing", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("frames vault open and all surface reads", async () => {
    const frames: Array<{ requestId: string; operation: string; payload: Record<string, unknown> }> = [];
    const transport: BridgeTransport = { request: async <T>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
      frames.push(frame);
      const result = frame.operation === "bridge.open_vault" ? { state: "opened" } : { surface: frame.payload.surface, job_id: "job", data: {} };
      return { protocol: "1.0", request_id: frame.requestId, ok: true, result: result as T };
    } };
    const client = createHostBridgeClient(transport);
    await client.openVault("/vault", "secret");
    await client.readOverview({ page: 1 });
    await client.readDocuments();
    await client.readReview({ limit: 2 });

    expect(frames.map((frame) => frame.requestId)).toEqual(["desktop-1", "desktop-2", "desktop-3", "desktop-4"]);
    expect(frames.map((frame) => frame.operation)).toEqual(["bridge.open_vault", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
    expect(frames[0].payload).toEqual({ vault_directory: "/vault", passphrase: "secret" });
    expect(frames[1].payload).toEqual({ surface: "overview", parameters: { page: 1 }, job_id: "desktop-overview-2" });
    expect(frames[2].payload).toEqual({ surface: "documents", parameters: {}, job_id: "desktop-documents-3" });
    expect(frames[3].payload).toEqual({ surface: "review", parameters: { limit: 2 }, job_id: "desktop-review-4" });
  });

  it("forwards the native folder picker without a sidecar frame", async () => {
    const frames: unknown[] = [];
    const client = createHostBridgeClient({
      request: async <T>(frame: BridgeRequest) => { frames.push(frame); return { protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }; },
      pickVaultDirectory: async () => "/chosen/local-vault",
    });
    await expect(client.pickVaultDirectory?.()).resolves.toBe("/chosen/local-vault");
    expect(frames).toEqual([]);
  });

  it("bounds missing results and failed bridge envelopes", async () => {
    const missing = createHostBridgeClient({ request: async () => ({ protocol: "1.0", request_id: "req", ok: true }) });
    const failed = createHostBridgeClient({ request: async () => ({ protocol: "1.0", request_id: "req", ok: false, error: { code: "vault_open_failed", message: "bounded failure" } }) });
    await expect(missing.openVault("/vault", "secret")).rejects.toThrow("desktop bridge request failed");
    await expect(failed.openVault("/vault", "secret")).rejects.toThrow("bounded failure");
  });

  it("detects only the installed window transport", () => {
    expect(hasHostBridge()).toBe(false);
    expect(createDetectedBridgeClient()).toBeNull();
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) };
    expect(hasHostBridge()).toBe(true);
    expect(createDetectedBridgeClient()).not.toBeNull();
  });
});
