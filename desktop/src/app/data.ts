import { createDetectedBridgeClient, createFixtureBridgeClient, type BridgeClient } from "./bridge-client";
import { demoState, type DemoState } from "./model";

export type SurfaceDataSource = {
  id: "synthetic-demo" | "bridge-client";
  label: string;
  description: string;
  boundary: "fixture" | "bridge-ready";
  load: () => Promise<DemoState>;
};

// The shell consumes this boundary so a sidecar-backed source can replace the
// fixture without changing navigation or feature components.
export const syntheticSurfaceData: SurfaceDataSource = {
  id: "synthetic-demo",
  label: "Synthetic local corpus",
  description: "Offline demo vault seeded from checked-in fixtures.",
  boundary: "fixture",
  load: async () => demoState,
};

export const detectedSurfaceData: SurfaceDataSource =
  typeof window !== "undefined" && window.orionVivaBridge
    ? createBridgeReadySource(createDetectedBridgeClient())
    : syntheticSurfaceData;

export function createBridgeReadySource(client: BridgeClient = createFixtureBridgeClient()): SurfaceDataSource {
  return {
    id: "bridge-client",
    label: "Bridge-facing surface adapter",
    description: "Typed host transport for an opened local vault; fixtures remain available for preview and tests.",
    boundary: "bridge-ready",
    load: () => client.snapshot(),
  };
}

export async function readSurface(source: SurfaceDataSource): Promise<DemoState> {
  return source.load();
}
