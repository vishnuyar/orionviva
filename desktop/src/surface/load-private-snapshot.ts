import { BridgeRefusal, BridgeUnreadable, REQUEST_REFUSED } from "../bridge/contracts";
import type { BridgeClient } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptOverview, adaptOverviewPanel } from "./adapters/overview";
import { adaptActionOutcome, adaptReview } from "./adapters/review";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { ActionResult, FeatureResult, OverviewData, ReviewActions, ReviewData, SurfaceSnapshot } from "./types";

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
  const [overviewRead, documentsRead, reviewRead] = await Promise.allSettled([client.readOverview(), client.readDocuments(), client.readReview()]);
  return buildLiveSnapshot(
    settledOverview(overviewRead),
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(reviewRead, (read) => adaptReview(read.data)),
  );
}
