import type { BridgeClient, SampleFrame } from "../bridge/contracts";
import { loadCoherentSnapshot, privateAccountingReader, loadPrivateDestination, loadPrivateSnapshot, loadPrioritySnapshot, loadStartupSecondarySnapshot, privateAccountLedgerReader, privateActivityActions, privateConversationActions, privateDocumentActions, privateJobStream, privateOverviewActions, privatePlanActions, privateSettingsActions, privateSpendingBreakdownReader, privateTransferActions, privateTrustActions, readEngineIdentity, readJobsFeature, readSurfaceRegistry, readUpdateLifecycle } from "./load-private-snapshot";
import type { PrioritySnapshot } from "./load-private-snapshot";
import type { AccountLedgerReader, ActivityActions, DocumentActions, EngineIdentity, FeatureResult, JobsData, JobStream, OverviewActions, ConversationActions, PlanActions, SettingsActions, SpendingBreakdownReader, SurfaceRegistry, TrustActions, SurfaceSnapshot, UpdateLifecycleView, VaultTransferActions } from "./types";

// Sample and private vaults share the sidecar, read adapters and source type.
// The engine creates the on-disk sample vault. `sample` carries the sidecar
// identity into the shell frame; feature rendering uses the same read data.
export type SurfaceSource = { id: "bridge-client"; label: string; description: string; sample: boolean; frame: SampleFrame | null; load: (activityLimit?: number, activityFocus?: string) => Promise<SurfaceSnapshot>; loadCoherent?: (activityLimit?: number, activityFocus?: string, start?: PrioritySnapshot, refresh?: boolean) => ReturnType<typeof loadCoherentSnapshot>; loadPriority?: (refresh?: boolean) => ReturnType<typeof loadPrioritySnapshot>; loadSecondary?: (activityLimit?: number, activityFocus?: string) => Promise<SurfaceSnapshot>; loadDestination?: (destination: "documents" | "review" | "trust" | "activity" | "plans", activityLimit?: number, activityFocus?: string) => Promise<Partial<SurfaceSnapshot>>; loadJobs?: () => Promise<FeatureResult<JobsData>>; accountingReader?: import("./types").AccountingReader | null; accountLedgerReader?: AccountLedgerReader | null; spendingBreakdownReader?: SpendingBreakdownReader | null; overviewActions?: OverviewActions | null; activityActions: ActivityActions; planActions?: PlanActions | null; documentActions: DocumentActions | null; jobStream: JobStream | null; transferActions: VaultTransferActions | null; settingsActions: SettingsActions | null; conversationActions: ConversationActions | null; trustActions: TrustActions | null; describe: () => Promise<SourceDescription> };
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
    // Carry the opened vault label and description with each source read.
    load: (activityLimit, activityFocus) => loadPrivateSnapshot(client, { title: label, subtitle, detail: description }, activityLimit, activityFocus),
    loadCoherent: (activityLimit, activityFocus, start, refresh) => loadCoherentSnapshot(client, { title: label, subtitle, detail: description }, activityLimit, activityFocus, start, refresh),
    loadPriority: (refresh) => loadPrioritySnapshot(client, { title: label, subtitle, detail: description }, refresh),
    loadSecondary: (activityLimit, activityFocus) => loadStartupSecondarySnapshot(client, { title: label, subtitle, detail: description }, activityLimit, activityFocus),
    loadDestination: (destination, activityLimit, activityFocus) => loadPrivateDestination(client, destination, activityLimit, activityFocus),
    loadJobs: () => readJobsFeature(client),
    accountingReader: privateAccountingReader(client),
    accountLedgerReader: privateAccountLedgerReader(client),
    spendingBreakdownReader: privateSpendingBreakdownReader(client),
    overviewActions: privateOverviewActions(client),
    activityActions: privateActivityActions(client),
    planActions: privatePlanActions(client),
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
// A sample source requires the sidecar-supplied frame.
export function sampleSource(client: BridgeClient, frame: SampleFrame): SurfaceSource { return vaultSource(client, frame); }
