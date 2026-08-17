import { describe, expect, it } from "vitest";
import { createFixtureBridgeClient, createHostBridgeClient, hasHostBridge } from "./bridge-client";
import { demoState } from "./model";

describe("bridge client boundary", () => {
  it("maps the fixture snapshot through the typed response contract", async () => {
    const snapshot = await createFixtureBridgeClient().snapshot();

    expect(snapshot).toBe(demoState);
    expect(snapshot.documents).toEqual(demoState.documents);
    expect(snapshot.reviewCount).toBe(demoState.reviewCount);
  });

  it("falls back to the supplied fixture when no host bridge exists", async () => {
    const fallback = { ...demoState, currentThrough: "Fallback fixture" };

    await expect(createFixtureBridgeClient(fallback).snapshot()).resolves.toBe(fallback);
  });

  it("requests vault lifecycle and all three reviewed surfaces through the host transport", async () => {
    const requests: Array<{ operation: string; payload: Record<string, unknown> }> = [];
    const transport = {
      request: async <T>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        requests.push({ operation, payload });
        const surface = payload.surface as string | undefined;
        const result = operation === "bridge.open_vault"
          ? { state: "opened" }
          : { surface, job_id: "job-1", data: { state: "ready" } };
        return { protocol: "1.0", request_id: "req", ok: true, result: result as T };
      },
    };

    const client = createHostBridgeClient(transport);
    await client.openVault("/vault", "secret");
    await client.readOverview();
    await client.readDocuments();
    await client.readReview();

    expect(requests.map(({ operation }) => operation)).toEqual([
      "bridge.open_vault",
      "viva.surface.read",
      "viva.surface.read",
      "viva.surface.read",
    ]);
    expect(requests[0].payload).toEqual({ vault_directory: "/vault", passphrase: "secret" });
    expect(requests.slice(1).map(({ payload }) => payload.surface)).toEqual([
      "overview", "documents", "review",
    ]);
  });

  it("keeps the native command boundary JSON-lines shaped", async () => {
    const frames: Array<{
      requestId: string;
      operation: string;
      payload: Record<string, unknown>;
    }> = [];
    const transport = {
      request: async <T>(frame: {
        requestId: string;
        operation: string;
        payload: Record<string, unknown>;
      }) => {
        frames.push(frame);
        const result = frame.operation === "bridge.open_vault"
          ? { state: "opened" }
          : { surface: frame.payload.surface, job_id: "job-1", data: {} };
        return {
          protocol: "1.0",
          request_id: frame.requestId,
          ok: true,
          result: result as T,
        };
      },
    };

    const client = createHostBridgeClient(transport);
    await client.openVault("/vault", "secret");
    await client.readOverview({ page: 1 });

    expect(frames).toEqual([
      {
        requestId: "desktop-1",
        operation: "bridge.open_vault",
        payload: { vault_directory: "/vault", passphrase: "secret" },
      },
      {
        requestId: "desktop-2",
        operation: "viva.surface.read",
        payload: {
          surface: "overview",
          parameters: { page: 1 },
          job_id: "desktop-overview-2",
        },
      },
    ]);
  });

  it("reports a bounded host error without exposing the bridge response", async () => {
    const transport = {
      request: async <T>() => ({
        protocol: "1.0",
        request_id: "req",
        ok: false,
        error: { code: "vault_open_failed", message: "internal path and credential details" },
      } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string } }),
    };

    await expect(createHostBridgeClient(transport).openVault("/vault", "secret"))
      .rejects.toThrow("internal path and credential details");
    expect(hasHostBridge()).toBe(false);
  });
});
