import { BridgeRefusal, BridgeTimeout, BridgeUnreadable, REQUEST_REFUSED } from "../bridge/contracts";
import type { BridgeClient, PriorityReadResult } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptActivity, adaptActivityActionOutcome } from "./adapters/activity";
import { adaptAccountLedger } from "./adapters/account-ledger";
import { adaptIdentity, adaptRegistry } from "./adapters/capabilities";
import { adaptConversation, adaptTurn } from "./adapters/conversation";
import { isRecord } from "./adapters/primitives";
import { adaptJobs, adaptProgress } from "./adapters/jobs";
import { adaptRescan } from "./adapters/rescan";
import { adaptLifecycle } from "./adapters/lifecycle";
import { adaptProposal, adaptSettings } from "./adapters/settings";
import { adaptTrust } from "./adapters/trust";
import { adaptAccounting, adaptOverview, adaptOverviewPanel } from "./adapters/overview";
import { adaptPlanDraftReply, adaptPlans } from "./adapters/plans";
import { adaptActionOutcome } from "./adapters/questions";
import { adaptReview } from "./adapters/review";
import { adaptSpendingBreakdown } from "./adapters/spending";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { AccountLedgerData, AccountLedgerReader, ActionResult, ActivityActionResult, ActivityActions, ActivityData, ConversationData, DocumentActions, DocumentsData, EngineIdentity, FeatureResult, JobStream, JobsData, OverviewActions, OverviewData, ConversationActions, PlanActions, SettingsActions, SpendingBreakdownData, SpendingBreakdownReader, SpendingRequest, SurfaceRegistry, TrustActions, TrustData, SurfaceSnapshot, UpdateLifecycleView, VaultTransferActions } from "./types";

function settled<TRaw, TData>(result: PromiseSettledResult<TRaw>, adapt: (raw: TRaw) => TData | null): FeatureResult<TData> {
  if (result.status === "rejected") return { state: "failed", reason: "read_failed" };
  const data = adapt(result.value);
  return data === null ? { state: "failed", reason: "invalid_payload" } : { state: "ready", data };
}
function settledPlans<TRaw extends { data: unknown }>(result: PromiseSettledResult<TRaw>): FeatureResult<import("./types").PlansData> {
  const adapted = settled(result, (read: TRaw) => adaptPlans(read.data));
  if (adapted.state !== "ready" || adapted.data.state !== "partial") return adapted;
  return { state: "partial", data: adapted.data, issues: [{ code: "plans_partial", message: "The plans read reported bounded history or availability detail." }] };
}
async function acted(call: Promise<unknown>): Promise<ActionResult> {
  const [replied] = await Promise.allSettled([call]);
  // Map request refusal to unserved and other channel failures to unanswered.
  // Exception messages remain outside the view data.
  if (replied.status === "rejected") {
    if (replied.reason instanceof BridgeTimeout) throw replied.reason;
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
    if (replied.reason instanceof BridgeTimeout) throw replied.reason;
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

async function requestActivityRead(client: BridgeClient, parameters: Record<string, string | number>) {
  try { return await client.readActivity(parameters); }
  catch (error) {
    if (parameters.cursor || !(error instanceof BridgeRefusal) || error.code !== REQUEST_REFUSED) throw error;
    const { page_version: _version, ...legacy } = parameters;
    return client.readActivity(legacy);
  }
}

function initialActivity(raw: unknown, focus = "") {
  const data = adaptActivity(raw, focus);
  return data?.page && data.page.cumulativeCount !== data.movements.length ? null : data;
}

async function readActivityFeature(client: BridgeClient, limit: number, cursor = "", focus = ""): Promise<FeatureResult<ActivityData>> {
  const parameters = { page_version: 1, limit, ...(cursor ? { cursor } : {}), ...(focus ? { focus } : {}) };
  const [read] = await Promise.allSettled([requestActivityRead(client, parameters)]);
  const result = settled(read, (value) => adaptActivity(value.data, focus));
  if ((result.state === "ready" || result.state === "partial" || result.state === "needs_input")
      && ((result.data.page && result.data.movements.length > limit)
          || (!cursor && result.data.page && result.data.page.cumulativeCount !== result.data.movements.length)
          || (cursor && !result.data.page))) return { state: "failed", reason: "invalid_payload" };
  return result;
}

export async function readAccountLedgerFeature(client: BridgeClient, accountId: string, cursor?: string, limit?: number): Promise<FeatureResult<AccountLedgerData>> {
  const [read] = await Promise.allSettled([client.readAccountLedger(accountId, cursor, limit)]);
  return settled(read, (value) => adaptAccountLedger(value.data));
}

export function privateAccountLedgerReader(client: BridgeClient): AccountLedgerReader {
  return { read: (accountId, cursor, limit) => readAccountLedgerFeature(client, accountId, cursor, limit) };
}

export async function readSpendingBreakdownFeature(client: BridgeClient, request: SpendingRequest): Promise<FeatureResult<SpendingBreakdownData>> {
  if (!client.readSpending) return { state: "unavailable", reason: "not_served" };
  const parameters = {
    period: request.period,
    granularity: request.granularity,
    ...(request.currency ? { currency: request.currency } : {}),
    ...(request.accountId ? { account_id: request.accountId } : {}),
    ...(request.startDate ? { start_date: request.startDate } : {}),
    ...(request.endDate ? { end_date: request.endDate } : {}),
  };
  const [read] = await Promise.allSettled([client.readSpending(parameters)]);
  return settled(read, (value) => adaptSpendingBreakdown(value.data));
}

export function privateSpendingBreakdownReader(client: BridgeClient): SpendingBreakdownReader {
  return { read: (request) => readSpendingBreakdownFeature(client, request) };
}

// Parse engine identity and registry payloads, requested once per opened source.
export async function readEngineIdentity(client: BridgeClient): Promise<FeatureResult<EngineIdentity>> {
  const [replied] = await Promise.allSettled([client.handshake()]);
  return settled(replied, adaptIdentity);
}

// Read update lifecycle once per source alongside identity and registry.
export async function readUpdateLifecycle(client: BridgeClient): Promise<FeatureResult<UpdateLifecycleView>> {
  const [replied] = await Promise.allSettled([client.readLifecycle()]);
  return settled(replied, adaptLifecycle);
}

export async function readSurfaceRegistry(client: BridgeClient): Promise<FeatureResult<SurfaceRegistry>> {
  const [replied] = await Promise.allSettled([client.readCapabilities()]);
  return settled(replied, adaptRegistry);
}

// Parse streamed sidecar progress into job rows; discard malformed frames.
export function privateJobStream(client: BridgeClient): JobStream | null {
  const subscribe = client.subscribeToJobProgress;
  if (!subscribe) return null;
  return (listen) => subscribe((frame) => {
    const job = adaptProgress(frame.result);
    // Only named registry operations enter the UI job stream.
    if (job?.operation.trim()) listen(job);
  });
}

// Document actions send one path per call without document bytes, then reread
// the vault-backed document list.
export function privateDocumentActions(client: BridgeClient): DocumentActions {
  return {
    upload: (path) => acted(client.uploadDocument(path)),
    recover: client.recoverDocument ? (jobId) => acted(client.recoverDocument!(jobId)) : undefined,
    reread: () => readDocumentsFeature(client),
    cancel: (jobId) => acted(client.cancelJob(jobId)),
    readJobs: () => readJobsFeature(client),
    // Keep channel outcome and rescan report separate. Parse a report only from
    // a settled reply.
    rescan: async () => {
      const [replied] = await Promise.allSettled([client.rescanDocuments()]);
      if (replied.status === "rejected" && replied.reason instanceof BridgeTimeout) throw replied.reason;
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
    ask: async (question, mirrored, planRequest = false, contextMode, movementIds) => {
      const [replied] = await Promise.allSettled([client.askViva(question, mirrored, planRequest, contextMode, movementIds)]);
      const result = await acted(Promise.resolve(replied.status === "fulfilled" ? replied.value : Promise.reject(replied.reason)));
      const turn = replied.status === "fulfilled" && isRecord(replied.value) ? adaptTurn(replied.value.state) : null;
      return { result, turn };
    },
    answer: (questionId, said) => acted(client.answerQuestion(questionId, said)),
    confirm: (proposalId, said, asked) => client.confirmProposal
      ? acted(client.confirmProposal(proposalId, said, asked))
      : Promise.resolve({ state: "unserved" }),
    decline: (questionId, reason) => acted(client.declineQuestion(questionId, reason)),
    undoCorrection: (correctionId) => client.undoAccountingCorrection
      ? acted(client.undoAccountingCorrection(correctionId))
      : Promise.resolve({ state: "unserved" }),
    reread: () => readConversationFeature(client),
    // Refresh Trust after a completed turn appends durable model-exchange records.
    rereadTrust: () => readTrustFeature(client),
  };
}

export function privateAccountingReader(client: BridgeClient): import("./types").AccountingReader | null {
  if (!client.readAccounting) return null;
  return async (start, end) => {
    const [result] = await Promise.allSettled([client.readAccounting!(start, end)]);
    return settled(result, (value) => adaptAccounting(value.data) ?? null);
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
      if (replied.status === "rejected" && replied.reason instanceof BridgeTimeout) throw replied.reason;
      const proposal = replied.status === "fulfilled" ? adaptProposal(replied.value) : null;
      if (proposal) return proposal;
      return acted(Promise.resolve(replied.status === "fulfilled" ? replied.value : Promise.reject(replied.reason)));
    },
    confirm: (kind, fields, digest, key) => acted(client.confirmSettings(kind, fields, digest, key)),
  };
}

// Export and restore send paths. Export leaves this vault unchanged; restore
// writes a different vault, so neither reloads this source.
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
    read: (limit, cursor, focus) => readActivityFeature(client, limit, cursor, focus),
    assignCategory: (movementId, categoryId) => activityActed(client.assignActivityCategory(movementId, categoryId)),
    assignClassification: (movementIds, categoryId, subcategoryId) => activityActed(client.assignActivityClassification(movementIds, categoryId, subcategoryId)),
    assignMeaning: (movementId, meaning, counterparty) => activityActed(client.assignActivityMeaning(movementId, meaning, counterparty)),
    replaceTags: (movementId, tagIds) => activityActed(client.replaceActivityTags(movementId, tagIds)),
    addTags: (movementIds, tagIds) => activityActed(client.addActivityTags(movementIds, tagIds)),
    removeTags: (movementIds, tagIds) => activityActed(client.removeActivityTags(movementIds, tagIds)),
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
      if (reply.status === "rejected" && reply.reason instanceof BridgeTimeout) throw reply.reason;
      if (reply.status === "rejected") return { state: "unanswered" };
      return adaptPlanDraftReply(reply.value);
    },
    propose: (payload) => acted(client.proposePlan(payload)),
    confirm: (proposalId) => acted(client.confirmPlan(proposalId)),
    decline: (proposalId) => acted(client.declinePlan(proposalId)),
  };
}

export type CoherentSnapshot = { snapshot: SurfaceSnapshot; revision: string };

export async function loadCoherentSnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], activityLimit?: number, activityFocus?: string, start?: PrioritySnapshot, refresh = false): Promise<CoherentSnapshot> {
  const first = await waitForPublication(client, disclosure, start ?? await loadPrioritySnapshot(client, disclosure, refresh));
  if (first.freshness !== "current" || !first.revision) throw new Error("aggregate_revision_unavailable");
  const activityParameters = { page_version: 1, limit: 50, ...(activityFocus ? { focus: activityFocus } : {}) };
  const [documentsRead, conversationRead, reviewRead, trustRead, activityRead, plansRead] = await Promise.allSettled([client.readDocuments(), client.readConversation(), client.readReview ? client.readReview() : Promise.reject(new Error("review_not_served")), client.readTrust(), requestActivityRead(client, activityParameters), client.readPlans()]);
  const confirmed = await loadPrioritySnapshot(client, disclosure);
  if (confirmed.freshness !== "current" || confirmed.revision !== first.revision) throw new Error("aggregate_revision_mismatch");
  return { revision: first.revision, snapshot: buildLiveSnapshot(
    first.snapshot.overview,
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(conversationRead, (read) => adaptConversation(read.data)),
    settled(trustRead, (read) => adaptTrust(read.data)),
    settled(activityRead, (read) => initialActivity(read.data, activityFocus)),
    settledPlans(plansRead),
    disclosure,
    settled(reviewRead, (read) => adaptReview(read.data)),
  ) };
}

export async function loadPrivateSnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], activityLimit?: number, activityFocus?: string): Promise<SurfaceSnapshot> {
  return (await loadCoherentSnapshot(client, disclosure, activityLimit, activityFocus)).snapshot;
}

export type PrioritySnapshot = { snapshot: SurfaceSnapshot; revision: string; freshness: "current" | "stale" | "unavailable"; lifecycle: string; retryable: boolean };

async function waitForPublication(client: BridgeClient, disclosure: SurfaceSnapshot["disclosure"] | undefined, initial: PrioritySnapshot): Promise<PrioritySnapshot> {
  let latest = initial;
  for (let attempt = 0; attempt < 240 && latest.freshness !== "current" && (latest.lifecycle === "stale" || latest.lifecycle === "rebuilding"); attempt += 1) {
    await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 250));
    // Observe publication without requesting synchronization on every poll.
    latest = await loadPrioritySnapshot(client, disclosure);
  }
  return latest;
}

export async function loadPrioritySnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], refresh = false): Promise<PrioritySnapshot> {
  const unavailable = (reason: "invalid_payload" | "read_failed" = "read_failed"): PrioritySnapshot => ({
    snapshot: buildLiveSnapshot(
      { state: "failed", reason },
      { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" },
      { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" },
      { state: "absent", reason: "reading" }, disclosure, { state: "absent", reason: "reading" }),
    revision: "", freshness: "unavailable", lifecycle: "degraded", retryable: true,
  });
  let reply;
  try { reply = await client.readOverviewAccounts(refresh); }
  catch { return unavailable(); }
  const raw = isRecord(reply.data) ? reply.data as unknown as PriorityReadResult : null;
  const valid = raw !== null
    && (raw.state === "ready" || raw.state === "stale" || raw.state === "degraded")
    && (raw.freshness === "current" || raw.freshness === "stale" || raw.freshness === "unavailable")
    && typeof raw.revision === "string" && typeof raw.lifecycle === "string" && typeof raw.error === "string"
    && JSON.stringify(raw.overview) === JSON.stringify(raw.accounts);
  if (!valid) return unavailable("invalid_payload");
  const overview = raw.overview !== null ? adaptOverview(raw.overview) : null;
  const coherentState = raw.state === "ready" && raw.freshness === "current";
  const retainedState = raw.state === "stale" && raw.freshness === "stale";
  const absentState = raw.state === "degraded" && raw.freshness === "unavailable";
  if ((!coherentState && !retainedState && !absentState)
      || ((coherentState || retainedState) && (!raw.revision || !overview))
      || (absentState && (raw.overview !== null || raw.accounts !== null))) return unavailable("invalid_payload");
  const panel = overview ? adaptOverviewPanel(raw.overview) : null;
  const result: FeatureResult<OverviewData> = overview
    ? panel && panel.state !== "ready"
      ? { state: panel.state as "partial" | "needs_input", data: overview, issues: panel.issues }
      : { state: "ready", data: overview }
    : { state: "failed", reason: "read_failed" };
  const priority: PrioritySnapshot = {
    snapshot: buildLiveSnapshot(result, { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" }, { state: "absent", reason: "reading" }, disclosure, { state: "absent", reason: "reading" }),
    revision: raw.revision, freshness: raw.freshness, lifecycle: raw.lifecycle,
    retryable: raw.state !== "ready",
  };
  return refresh ? waitForPublication(client, disclosure, priority) : priority;
}

export async function loadSecondarySnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], activityLimit?: number, activityFocus?: string): Promise<SurfaceSnapshot> {
  const activityParameters = { page_version: 1, limit: 50, ...(activityFocus ? { focus: activityFocus } : {}) };
  const [documentsRead, conversationRead, reviewRead, trustRead, activityRead, plansRead] = await Promise.allSettled([client.readDocuments(), client.readConversation(), client.readReview ? client.readReview() : Promise.reject(new Error("review_not_served")), client.readTrust(), requestActivityRead(client, activityParameters), client.readPlans()]);
  return buildLiveSnapshot(
    { state: "absent", reason: "priority_owned" },
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(conversationRead, (read) => adaptConversation(read.data)),
    settled(trustRead, (read) => adaptTrust(read.data)),
    settled(activityRead, (read) => initialActivity(read.data, activityFocus)),
    settledPlans(plansRead), disclosure,
    settled(reviewRead, (read) => adaptReview(read.data)),
  );
}

export async function loadStartupSecondarySnapshot(client: BridgeClient, disclosure?: SurfaceSnapshot["disclosure"], activityLimit?: number, activityFocus?: string): Promise<SurfaceSnapshot> {
  void client; void activityLimit; void activityFocus;
  return buildLiveSnapshot(
    { state: "absent", reason: "priority_owned" },
    { state: "absent", reason: "not_asked" },
    { state: "absent", reason: "not_asked" },
    { state: "absent", reason: "not_asked" },
    { state: "absent", reason: "not_asked" },
    { state: "absent", reason: "not_asked" }, disclosure,
    { state: "absent", reason: "not_asked" },
  );
}

export async function loadPrivateDestination(client: BridgeClient, destination: "documents" | "review" | "trust" | "activity" | "plans", activityLimit = 50, activityFocus = ""): Promise<Partial<SurfaceSnapshot>> {
  if (destination === "documents") return { documents: await readDocumentsFeature(client) };
  if (destination === "review") {
    const [review, conversation] = await Promise.allSettled([client.readReview ? client.readReview() : Promise.reject(new Error("review_not_served")), client.readConversation()]);
    return { review: settled(review, (value) => adaptReview(value.data)), conversation: settled(conversation, (value) => adaptConversation(value.data)) };
  }
  if (destination === "trust") return { trust: await readTrustFeature(client) };
  if (destination === "activity") return { activity: await readActivityFeature(client, 50, "", activityFocus) };
  const [read] = await Promise.allSettled([client.readPlans()]);
  return { plans: settledPlans(read) };
}
