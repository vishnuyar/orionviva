import type { BridgeClient } from "../bridge/contracts";
import { demoSnapshot } from "./fixtures/demo-snapshot";
import { loadPrivateSnapshot, privateReviewActions } from "./load-private-snapshot";
import type { ActionResult, ReviewActions, SurfaceMode, SurfaceSnapshot } from "./types";

// Every source carries the review verbs. The sample vault's verb always
// refuses, because nothing in it is recorded, which is also how the refusal a
// person may meet is reachable with no vault open. No source is without them,
// so no screen has a state where the controls are missing.
export type SurfaceSource = { id: "synthetic-demo" | "bridge-client"; label: string; description: string; boundary: "fixture" | "bridge-ready"; mode: SurfaceMode; load: () => Promise<SurfaceSnapshot>; reviewActions: ReviewActions };
export const sampleSnapshot = demoSnapshot;
const sampleRefusal = async (): Promise<ActionResult> => ({ state: "settled", outcome: { kind: "refused", message: "This is the sample vault, and nothing in it is recorded. This question was not set aside. Open your own vault to set one aside for real.", reason: "sample_vault" } });
const sampleReviewActions: ReviewActions = { decline: sampleRefusal, reread: async () => demoSnapshot.review };
export const demoSource: SurfaceSource = { id: "synthetic-demo", label: "Sample vault", description: "Every name, document, and figure in this vault is fictional and stored with the app.", boundary: "fixture", mode: "demo", load: async () => demoSnapshot, reviewActions: sampleReviewActions };
export function privateSource(client: BridgeClient): SurfaceSource { return { id: "bridge-client", label: "Private vault", description: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.", boundary: "bridge-ready", mode: "live", load: () => loadPrivateSnapshot(client), reviewActions: privateReviewActions(client) }; }
