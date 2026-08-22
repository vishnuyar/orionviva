import { BridgeRefusal, BridgeUnreadable, REQUEST_REFUSED } from "../bridge/contracts";
import type { BridgeClient } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptIdentity, adaptRegistry } from "./adapters/capabilities";
import { isRecord } from "./adapters/primitives";
import { adaptJobs, adaptProgress } from "./adapters/jobs";
import { adaptRescan } from "./adapters/rescan";
import { adaptTrust } from "./adapters/trust";
import { adaptOverview, adaptOverviewPanel } from "./adapters/overview";
import { adaptActionOutcome, adaptReview } from "./adapters/review";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { ActionResult, DocumentActions, DocumentsData, EngineIdentity, FeatureResult, JobStream, JobsData, OverviewData, ReviewActions, ReviewData, SurfaceRegistry, SurfaceSnapshot, VaultTransferActions } from "./types";

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

async function readReviewFeature(client: BridgeClient): Promise<FeatureResult<ReviewData>> {
  const [read] = await Promise.allSettled([client.readReview()]);
  return settled(read, (value) => adaptReview(value.data));
}

async function readDocumentsFeature(client: BridgeClient): Promise<FeatureResult<DocumentsData>> {
  const [read] = await Promise.allSettled([client.readDocuments()]);
  return settled(read, (value) => adaptDocuments(value.data));
}

async function readJobsFeature(client: BridgeClient): Promise<FeatureResult<JobsData>> {
  const [read] = await Promise.allSettled([client.readJobs()]);
  return settled(read, (value) => adaptJobs(value.data));
}

// What the sidecar declares about itself and about its own registry, read here
// like every other payload. Both are asked once when a vault opens: neither
// changes while one sidecar lives, and asking again per screen would be asking
// a settled question over and over.
export async function readEngineIdentity(client: BridgeClient): Promise<FeatureResult<EngineIdentity>> {
  const [replied] = await Promise.allSettled([client.handshake()]);
  return settled(replied, adaptIdentity);
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

// A whole vault out, and a whole vault back. Neither is followed by a read of
// this vault: the export does not change it, and the restore writes somewhere
// else entirely, so re-reading here would claim a change nothing made.
export function privateTransferActions(client: BridgeClient): VaultTransferActions {
  return {
    export: (archive) => acted(client.exportVault(archive)),
    restore: (archive, directory, passphrase) => acted(client.restoreVault(archive, directory, passphrase)),
  };
}

// The write side of the review capability, and the read that follows it. An
// action never throws at a screen: what came back is a result the screen can
// render, including the case where the reply could not be read at all.
export function privateReviewActions(client: BridgeClient): ReviewActions {
  return {
    decline: (questionId, reason) => acted(client.declineQuestion(questionId, reason)),
    reread: () => readReviewFeature(client),
  };
}

export async function loadPrivateSnapshot(client: BridgeClient): Promise<SurfaceSnapshot> {
  const [overviewRead, documentsRead, reviewRead, trustRead] = await Promise.allSettled([client.readOverview(), client.readDocuments(), client.readReview(), client.readTrust()]);
  return buildLiveSnapshot(
    settledOverview(overviewRead),
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(reviewRead, (read) => adaptReview(read.data)),
    settled(trustRead, (read) => adaptTrust(read.data)),
  );
}
