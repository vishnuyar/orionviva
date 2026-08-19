import type { BridgeClient } from "../bridge/contracts";
import { demoSnapshot } from "./fixtures/demo-snapshot";
import { loadPrivateSnapshot } from "./load-private-snapshot";
import type { SurfaceMode, SurfaceSnapshot } from "./types";

export type SurfaceSource = { id: "synthetic-demo" | "bridge-client"; label: string; description: string; boundary: "fixture" | "bridge-ready"; mode: SurfaceMode; load: () => Promise<SurfaceSnapshot> };
export const sampleSnapshot = demoSnapshot;
export const demoSource: SurfaceSource = { id: "synthetic-demo", label: "Sample vault", description: "Every name, document, and figure in this vault is fictional and stored with the app.", boundary: "fixture", mode: "demo", load: async () => demoSnapshot };
export function privateSource(client: BridgeClient): SurfaceSource { return { id: "bridge-client", label: "Private vault", description: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.", boundary: "bridge-ready", mode: "live", load: () => loadPrivateSnapshot(client) }; }
