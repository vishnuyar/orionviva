import { BridgeRefusal, BridgeUnreadable, REQUEST_REFUSED } from "../bridge/contracts";
import type { BridgeClient } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptActivity, adaptActivityActionOutcome } from "./adapters/activity";
import { adaptIdentity, adaptRegistry } from "./adapters/capabilities";
import { adaptConversation, adaptTurn } from "./adapters/conversation";
import { isRecord } from "./adapters/primitives";
import { adaptJobs, adaptProgress } from "./adapters/jobs";
import { adaptRescan } from "./adapters/rescan";
import { adaptLifecycle } from "./adapters/lifecycle";
import { adaptProposal, adaptSettings } from "./adapters/settings";
import { adaptTrust } from "./adapters/trust";
import { adaptOverview, adaptOverviewPanel } from "./adapters/overview";
import { adaptPlanDraftReply, adaptPlans } from "./adapters/plans";
import { adaptActionOutcome } from "./adapters/questions";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { ActionResult, ActivityActionResult, ActivityActions, ActivityData, ConversationData, DocumentActions, DocumentsData, EngineIdentity, FeatureResult, JobStream, JobsData, OverviewActions, OverviewData, ConversationActions, PlanActions, SettingsActions, SurfaceRegistry, TrustActions, TrustData, SurfaceSnapshot, UpdateLifecycleView, VaultTransferActions } from "./types";

function settled<TRaw, TData>(result: PromiseSettledResult<TRaw>, adapt: (raw: TRaw) => TData | null): FeatureResult<TData> {
  if (result.status === "rejected") return { state: "failed", reason: "read_failed" };
  const data = adapt(result.value);
  return data === null ? { state: "failed", reason: "invalid_payload" } : { state: "ready", data };
}
// The panel state is taken from what the overview reported about itself, not
// decided here from the adapted rows.
function settledOverview<TRaw extends { data: unknown }>(result: PromiseSettledResult<TRaw>): FeatureResult<OverviewData> {
  const adapted = settled(result, (read: TRaw) => adaptOverview(read.data));
  if (adapted.state !== "ready") return adapted;
  const panel = adaptOverviewPanel((result as PromiseFulfilledResult<TRaw>).value.data);
  return panel.state === "ready" ? adapted : { state: panel.state as "partial" | "needs_input", data: adapted.data, issues: panel.issues };
}
function settledPlans<TRaw extends { data: unknown }>(result: PromiseSettledResult<TRaw>): FeatureResult<import("./types").PlansData> {
  const adapted = settled(result, (read: TRaw) => adaptPlans(read.data));
  if (adapted.state !== "ready" || adapted.data.state !== "partial") return adapted;
  return { state: "partial", data: adapted.data, issues: [{ code: "plans_partial", message: "The plans read reported bounded history or availability detail." }] };
}
async function acted(call: Promise<unknown>): Promise<ActionResult> {
  const [replied] = await Promise.allSettled([call]);
  // Which channel answered, decided here and nowhere else. The one code the
  // sidecar means as "this request will not be taken" is the request being
  // refused; every other code says the frame was never served.
  //
  // No message from any of them is carried out of here. The protocol puts the
  // text of an exception a handler raised into that field, and an exception
  // raised inside the engine can carry a merchant name, an account name or an
  // amount read out of the vault — vault text reaching a screen ungraded,
  // uncited and through no read model.
  if (replied.status === "rejected") {
    if (replied.reason instanceof BridgeRefusal) return replied.reason.code === REQUEST_REFUSED ? { state: "unserved" } : { state: "unreadable" };
    if (replied.reason instanceof BridgeUnreadable) return { state: "unreadable" };
    return { state: "unanswered" };
  }
  const outcome = adaptActionOutcome(replied.value);
  return outcome === null ? { state: "unreadable" } : { state: "settled", outcome };
}

async function activityActed(call: Promise<unknown>): Promise<ActivityActionResult> {
  const [replied] = await Promise.allSettled([call]);
  if (replied.status === "rejected") {
    if (replied.reason instanceof BridgeRefusal) return replied.reason.code === REQUEST_REFUSED ? { state: "unserved" } : { state: "unreadable" };
    if (replied.reason instanceof BridgeUnreadable) return { state: "unreadable" };
    return { state: "unanswered" };
  }
  const outcome = adaptActivityActionOutcome(replied.value);
  return outcome ? { state: "settled", outcome } : { state: "unreadable" };
}

async function readConversationFeature(client: BridgeClient): Promise<FeatureResult<ConversationData>> {
  const [read] = await Promise.allSettled([client.readConversation()]);
  return settled(read, (value) => adaptConversation(value.data));
}

async function readDocumentsFeature(client: BridgeClient): Promise<FeatureResult<DocumentsData>> {
  const [read] = await Promise.allSettled([client.readDocuments()]);
  return settled(read, (value) => adaptDocuments(value.data));
}

export async function readJobsFeature(client: BridgeClient): Promise<FeatureResult<JobsData>> {
  const [read] = await Promise.allSettled([client.readJobs()]);
  return settled(read, (value) => adaptJobs(value.data));
}

async function readTrustFeature(client: BridgeClient): Promise<FeatureResult<TrustData>> {
  const [read] = await Promise.allSettled([client.readTrust()]);
  return settled(read, (value) => adaptTrust(value.data));
}

async function readActivityFeature(client: BridgeClient, limit: number): Promise<FeatureResult<ActivityData>> {
  const [read] = await Promise.allSettled([client.readActivity({ limit })]);
  return settled(read, (value) => adaptActivity(value.data));
}

// What the sidecar declares about itself and about its own registry, read here
// like every other payload. Both are asked once when a vault opens: neither
// changes while one sidecar lives, and asking again per screen would be asking
// a settled question over and over.
export async function readEngineIdentity(client: BridgeClient): Promise<FeatureResult<EngineIdentity>> {
  const [replied] = await Promise.allSettled([client.handshake()]);
  return settled(replied, adaptIdentity);
}

// What happens to this application when a new version exists. Asked once per
// source like the handshake and the registry: it is a fact about the build
// rather than about the vault, and it does not change while one sidecar lives.
export async function readUpdateLifecycle(client: BridgeClient): Promise<FeatureResult<UpdateLifecycleView>> {
  const [replied] = await Promise.allSettled([client.readLifecycle()]);
  return settled(replied, adaptLifecycle);
}

export async function readSurfaceRegistry(client: BridgeClient): Promise<FeatureResult<SurfaceRegistry>> {
  const [replied] = await Promise.allSettled([client.readCapabilities()]);
  return settled(replied, adaptRegistry);
}

// What the sidecar says it is doing, as it does it, already read into the
// shape a screen holds. The frame is opened here rather than above this line
// for the same reason every other payload is: nothing over the boundary reads
// a raw shape, and a frame this side cannot read is dropped rather than
// rendered under the nearest word.
export function privateJobStream(client: BridgeClient): JobStream | null {
  const subscribe = client.subscribeToJobProgress;
  if (!subscribe) return null;
  return (listen) => subscribe((frame) => {
    const job = adaptProgress(frame.result);
    if (job) listen(job);
  });
}

// The write side of the documents capability, and the read that follows it.
// One path crosses per call and no bytes ever do; the vault is read again
// afterwards so the list a person sees is the vault's own, not this screen's
// idea of what it just did.
export function privateDocumentActions(client: BridgeClient): DocumentActions {
  return {
    upload: (path) => acted(client.uploadDocument(path)),
    reread: () => readDocumentsFeature(client),
    cancel: (jobId) => acted(client.cancelJob(jobId)),
    readJobs: () => readJobsFeature(client),
    // Two answers from one frame, kept apart. `result` is which channel spoke
    // and what the vault said; `report` is what the pass did, and it is read
    // only from a reply the vault itself settled — a channel that never
    // answered has nothing to report about.
    rescan: async () => {
      const [replied] = await Promise.allSettled([client.rescanDocuments()]);
      const result = await acted(Promise.resolve(replied.status === "fulfilled" ? replied.value : Promise.reject(replied.reason)));
      const report = replied.status === "fulfilled" && isRecord(replied.value) ? adaptRescan(replied.value.state) : null;
      return { result, report };
    },
  };
}

// One question, and the turn it produced. Two answers from one frame, kept
// apart: `result` is which channel spoke and what the vault said; `turn` is the
// turn itself, read only from a reply the vault settled.
export function privateConversationActions(client: BridgeClient): ConversationActions {
  return {
    ask: async (question, mirrored, planRequest = false) => {
      const [replied] = await Promise.allSettled([client.askViva(question, mirrored, planRequest)]);
      const result = await acted(Promise.resolve(replied.status === "fulfilled" ? replied.value : Promise.reject(replied.reason)));
      const turn = replied.status === "fulfilled" && isRecord(replied.value) ? adaptTurn(replied.value.state) : null;
      return { result, turn };
    },
    answer: (questionId, said) => acted(client.answerQuestion(questionId, said)),
    confirm: (proposalId, said, asked) => client.confirmProposal
      ? acted(client.confirmProposal(proposalId, said, asked))
      : Promise.resolve({ state: "unserved" }),
    decline: (questionId, reason) => acted(client.declineQuestion(questionId, reason)),
    reread: () => readConversationFeature(client),
    // A completed turn durably appends one outbound event per model exchange.
    // Read Trust after the turn so the snapshot cannot remain the one taken
    // when the vault first opened.
    rereadTrust: () => readTrustFeature(client),
  };
}

// Trust actions return an immediate run or enqueue receipt; the session then
// rereads the financial surfaces and durable job registry.
export function privateTrustActions(client: BridgeClient): TrustActions {
  return {
    run: (spend) => acted(client.runMaintenance(spend)),
    diagnose: (file) => acted(client.writeDiagnostic(file)),
  };
}

// What this machine has been told to do, and the yes that tells it. Proposing
// changes nothing: what comes back is either the proposal a person is shown, or
// the channel's own answer about why there is none.
export function privateSettingsActions(client: BridgeClient): SettingsActions {
  return {
    read: async () => {
      const [replied] = await Promise.allSettled([client.readSettings()]);
      return settled(replied, adaptSettings);
    },
    propose: async (kind, fields) => {
      const [replied] = await Promise.allSettled([client.proposeSettings(kind, fields)]);
      const proposal = replied.status === "fulfilled" ? adaptProposal(replied.value) : null;
      if (proposal) return proposal;
      return acted(Promise.resolve(replied.status === "fulfilled" ? replied.value : Promise.reject(replied.reason)));
    },
    confirm: (kind, fields, digest, key) => acted(client.confirmSettings(kind, fields, digest, key)),
  };
}

// A whole vault out, and a whole vault back. Neither is followed by a read of
// this vault: the export does not change it, and the restore writes somewhere
// else entirely, so re-reading here would claim a change nothing made.
export function privateTransferActions(client: BridgeClient): VaultTransferActions {
  return {
    export: (archive) => acted(client.exportVault(archive)),
    restore: (archive, directory, passphrase) => acted(client.restoreVault(archive, directory, passphrase)),
  };
}

// Movement corrections carry only the durable movement identity and the
// complete desired value. The action reply is deliberately not treated as a
// read: every surface is read again by the session after it arrives.
export function privateActivityActions(client: BridgeClient): ActivityActions {
  return {
    read: (limit) => readActivityFeature(client, limit),
    assignCategory: (movementId, categoryId) => activityActed(client.assignActivityCategory(movementId, categoryId)),
    assignMeaning: (movementId, meaning, counterparty) => activityActed(client.assignActivityMeaning(movementId, meaning, counterparty)),
    replaceTags: (movementId, tagIds) => activityActed(client.replaceActivityTags(movementId, tagIds)),
    confirmTransfer: (movementId, counterpartId) => activityActed(client.confirmActivityTransfer(movementId, counterpartId)),
    rejectTransfer: (movementId) => activityActed(client.rejectActivityTransfer(movementId)),
    unlinkTransfer: (movementId, counterpartId) => activityActed(client.unlinkActivityTransfer(movementId, counterpartId)),
  };
}

export function privateOverviewActions(client: BridgeClient): OverviewActions | null {
  return client.setAsideFinding ? { setAsideFinding: (findingId) => acted(client.setAsideFinding!(findingId)) } : null;
}

export function privatePlanActions(client: BridgeClient): PlanActions {
  return {
    draft: async (payload) => {
      const [reply] = await Promise.allSettled([client.draftPlan(payload)]);
      if (reply.status === "rejected") return { state: "unanswered" };
      return adaptPlanDraftReply(reply.value);
    },
    propose: (payload) => acted(client.proposePlan(payload)),
    confirm: (proposalId) => acted(client.confirmPlan(proposalId)),
    decline: (proposalId) => acted(client.declinePlan(proposalId)),
  };
}

export async function loadPrivateSnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], activityLimit?: number, activityFocus?: string): Promise<SurfaceSnapshot> {
  const activityParameters = { ...(activityLimit ? { limit: activityLimit } : {}), ...(activityFocus ? { focus: activityFocus } : {}) };
  const [overviewRead, documentsRead, conversationRead, trustRead, activityRead, plansRead] = await Promise.allSettled([client.readOverview(), client.readDocuments(), client.readConversation(), client.readTrust(), client.readActivity(Object.keys(activityParameters).length ? activityParameters : undefined), client.readPlans()]);
  return buildLiveSnapshot(
    settledOverview(overviewRead),
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(conversationRead, (read) => adaptConversation(read.data)),
    settled(trustRead, (read) => adaptTrust(read.data)),
    settled(activityRead, (read) => adaptActivity(read.data)),
    settledPlans(plansRead),
    disclosure,
  );
}
