import type { BridgeClient } from "../bridge/contracts";
import { demoSnapshot } from "./fixtures/demo-snapshot";
import { loadPrivateSnapshot, privateConversationActions, privateDocumentActions, privateJobStream, privateReviewActions, privateSettingsActions, privateTransferActions, privateTrustActions, readEngineIdentity, readSurfaceRegistry } from "./load-private-snapshot";
import type { ActionResult, Destination, DocumentActions, EngineIdentity, FeatureResult, JobStream, ReviewActions, SurfaceMode, ConversationActions, SettingsActions, SurfaceRegistry, TrustActions, SurfaceSnapshot, VaultTransferActions } from "./types";

// Every source carries the review verbs. The sample vault's verb always
// refuses, because nothing in it is recorded, which is also how the refusal a
// person may meet is reachable with no vault open. No source is without them,
// so no screen has a state where the controls are missing.
// The capture verb is not on every source. The sample vault cannot take a
// file at all, so it carries none and the screen it feeds renders no control
// rather than one that would have to refuse.
export type SurfaceSource = { id: "synthetic-demo" | "bridge-client"; label: string; description: string; boundary: "fixture" | "bridge-ready"; mode: SurfaceMode; load: () => Promise<SurfaceSnapshot>; reviewActions: ReviewActions; documentActions: DocumentActions | null; jobStream: JobStream | null; transferActions: VaultTransferActions | null; settingsActions: SettingsActions | null; conversationActions: ConversationActions | null; trustActions: TrustActions | null; describe: () => Promise<SourceDescription> };
// What a source says about the engine behind it: which build answered, and
// which destinations its registry says a read reaches. The sample vault has no
// engine behind it, so it answers with the one honest thing it can — a fixture
// naming itself as one.
export type SourceDescription = { identity: FeatureResult<EngineIdentity>; registry: FeatureResult<SurfaceRegistry> };
// Every destination this shell has a screen for, and the sample vault's answer
// about each: the fixture serves them all, because everything on those screens
// comes out of it. It is a claim about a fixture and is labelled as one
// everywhere it is shown.
const sampleServed: Record<Destination, boolean> = { overview: true, accounts: true, activity: true, documents: true, review: true, trust: true };
export const sampleSnapshot = demoSnapshot;
const sampleRefusal = async (): Promise<ActionResult> => ({ state: "settled", outcome: { kind: "refused", message: "This is the sample vault, and nothing in it is recorded. This question was not set aside. Open your own vault to set one aside for real.", reason: "sample_vault" } });
const sampleReviewActions: ReviewActions = { answer: sampleRefusal, decline: sampleRefusal, reread: async () => demoSnapshot.review };
export const demoSource: SurfaceSource = { id: "synthetic-demo", label: "Sample vault", description: "Every name, document, and figure in this vault is fictional and stored with the app.", boundary: "fixture", mode: "demo", load: async () => demoSnapshot, reviewActions: sampleReviewActions, documentActions: null, jobStream: null, transferActions: null, settingsActions: null, conversationActions: null, trustActions: null, describe: async () => ({ identity: { state: "unavailable", reason: "sample_vault" }, registry: { state: "ready", data: { served: sampleServed, undeclared: [] } } }) };
export function privateSource(client: BridgeClient): SurfaceSource { return { id: "bridge-client", label: "Private vault", description: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.", boundary: "bridge-ready", mode: "live", load: () => loadPrivateSnapshot(client), reviewActions: privateReviewActions(client), documentActions: privateDocumentActions(client), jobStream: privateJobStream(client), transferActions: privateTransferActions(client), settingsActions: privateSettingsActions(client), conversationActions: privateConversationActions(client), trustActions: privateTrustActions(client), describe: async () => {
  const [identity, registry] = await Promise.all([readEngineIdentity(client), readSurfaceRegistry(client)]);
  return { identity, registry };
} }; }
