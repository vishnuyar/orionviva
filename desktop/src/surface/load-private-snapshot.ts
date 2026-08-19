import type { BridgeClient } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptOverview, adaptOverviewPanel } from "./adapters/overview";
import { adaptReview } from "./adapters/review";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { FeatureResult, OverviewData, SurfaceSnapshot } from "./types";

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
export async function loadPrivateSnapshot(client: BridgeClient): Promise<SurfaceSnapshot> {
  const [overviewRead, documentsRead, reviewRead] = await Promise.allSettled([client.readOverview(), client.readDocuments(), client.readReview()]);
  return buildLiveSnapshot(
    settledOverview(overviewRead),
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(reviewRead, (read) => adaptReview(read.data)),
  );
}
