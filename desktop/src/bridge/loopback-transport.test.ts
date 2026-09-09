import { afterEach, describe, expect, it, vi } from "vitest";
import { createLoopbackTransport } from "./loopback-transport";

afterEach(() => vi.unstubAllGlobals());

describe("the loopback-only web bridge", () => {
  it("installs only on the numeric loopback host with a capability token", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ protocol: "2.0", request_id: "request-1", ok: true, result: {} }),
    });
    vi.stubGlobal("fetch", fetch);

    const transport = createLoopbackTransport(
      { hostname: "127.0.0.1", hash: "#token=synthetic-token" },
      fetch,
    );
    expect(transport).not.toBeNull();
    await transport!.request({ requestId: "request-1", operation: "bridge.handshake", payload: {} });
    expect(fetch).toHaveBeenCalledWith("/__orionviva/bridge", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ authorization: "Bearer synthetic-token" }),
    }));
  });

  it("refuses an ordinary web host", () => {
    expect(createLoopbackTransport({ hostname: "localhost", hash: "#token=synthetic-token" }, fetch)).toBeNull();
  });
});
