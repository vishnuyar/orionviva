import type { BridgeClient, SampleFrame } from "../bridge/contracts";
import { loadPrivateSnapshot, privateActivityActions, privateConversationActions, privateDocumentActions, privateJobStream, privateOverviewActions, privateReviewActions, privateSettingsActions, privateTransferActions, privateTrustActions, readEngineIdentity, readSurfaceRegistry, readUpdateLifecycle } from "./load-private-snapshot";
import type { ActivityActions, DocumentActions, EngineIdentity, FeatureResult, JobStream, OverviewActions, ReviewActions, ConversationActions, SettingsActions, SurfaceRegistry, TrustActions, SurfaceSnapshot, UpdateLifecycleView, VaultTransferActions } from "./types";

// One kind of source, because there is now one kind of vault.
//
// The sample used to be a second implementation of this type, loading fixtures
// composed in the shell, and every screen carried a second dialect to render
// it: a qualifier beside each figure and an authored fallback under each
// missing field. That is the design VOICE-139 calls the worse of two, and it
// is gone. The sample is a vault on disk, minted by the engine, opened through
// the same sidecar and read through the same adapters — so a screen has one
// way to draw a figure and no way to know which vault it came from.
//
// `sample` is what the sidecar said about the vault it opened, carried here so
// the shell can put one permanent frame around the place. It is not a
// rendering switch: no screen branches on it. This source uses it only to
// choose the permanent frame that says where a person is.
export type SurfaceSource = { id: "bridge-client"; label: string; description: string; sample: boolean; frame: SampleFrame | null; load: () => Promise<SurfaceSnapshot>; overviewActions?: OverviewActions | null; reviewActions: ReviewActions; activityActions: ActivityActions; documentActions: DocumentActions | null; jobStream: JobStream | null; transferActions: VaultTransferActions | null; settingsActions: SettingsActions | null; conversationActions: ConversationActions | null; trustActions: TrustActions | null; describe: () => Promise<SourceDescription> };
// What a source says about the engine behind it: which build answered, and
// which destinations its registry says a read reaches.
export type SourceDescription = { identity: FeatureResult<EngineIdentity>; registry: FeatureResult<SurfaceRegistry>; lifecycle: FeatureResult<UpdateLifecycleView> };

export function vaultSource(client: BridgeClient, frame: SampleFrame | null): SurfaceSource {
  const sample = frame !== null;
  const label = sample ? "Sample vault" : "Private vault";
  const subtitle = sample ? "Nothing here is real" : "Opened on this device";
  const description = sample
    ? "Every account, document, name and amount here was invented. Changes you make here do not change your own records."
    : "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.";
  return {
    id: "bridge-client",
    sample,
    frame,
    label,
    description,
    // Which vault a screen is looking at travels with the read rather than
    // being decided inside it, because the one place a wrong answer here
    // matters is the one the read cannot tell apart on its own.
    load: () => loadPrivateSnapshot(client, { title: label, subtitle, detail: description }),
    overviewActions: privateOverviewActions(client),
    reviewActions: privateReviewActions(client),
    activityActions: privateActivityActions(client),
    documentActions: privateDocumentActions(client),
    jobStream: privateJobStream(client),
    transferActions: privateTransferActions(client),
    settingsActions: privateSettingsActions(client),
    conversationActions: privateConversationActions(client),
    trustActions: privateTrustActions(client),
    describe: async () => {
      const [identity, registry, lifecycle] = await Promise.all([readEngineIdentity(client), readSurfaceRegistry(client), readUpdateLifecycle(client)]);
      return { identity, registry, lifecycle };
    },
  };
}

export function privateSource(client: BridgeClient): SurfaceSource { return vaultSource(client, null); }
// A sample source exists only where the sidecar sent the frame's words. There
// is no path here that makes one without them, so there is no state in which
// somebody is inside the sample vault with nothing around it saying so.
export function sampleSource(client: BridgeClient, frame: SampleFrame): SurfaceSource { return vaultSource(client, frame); }
