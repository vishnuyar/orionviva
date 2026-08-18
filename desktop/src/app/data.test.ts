import { describe, expect, it } from "vitest";
import { createFixtureBridgeClient } from "./bridge-client";
import { createBridgeReadySource, detectedSurfaceData, syntheticSurfaceData } from "./data";

describe("surface data boundary", () => {
  it("keeps the fixture-backed preview path as the default", async () => {
    const preview = await syntheticSurfaceData.load();
    expect(preview.currentThrough).toBe("July 31, 2026");
    expect(syntheticSurfaceData.boundary).toBe("fixture");
  });

  it("detects the fixture fallback when no host bridge is injected", () => {
    expect(detectedSurfaceData).toBe(syntheticSurfaceData);
  });

  it("exposes a typed bridge-ready adapter seam", async () => {
    const source = createBridgeReadySource();
    const preview = await source.load();

    expect(source.id).toBe("bridge-client");
    expect(source.boundary).toBe("bridge-ready");
    expect(source.description).toMatch(/opened local vault/i);
    expect(preview.corpusSource).toBe("Synthetic local corpus · generated from the merchant catalog");
  });

  it("can load a snapshot from a typed bridge client", async () => {
    const source = createBridgeReadySource(createFixtureBridgeClient());
    const preview = await source.load();

    expect(source.boundary).toBe("bridge-ready");
    expect(preview.reviewCount).toBe(2);
    expect(preview.netWorth.display).toBe("$48,240.18");
  });
});
